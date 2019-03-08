import torch
import torch.nn as nn
# from torch._six import inf
from torch.distributions.normal import Normal
from torch.distributions.multivariate_normal import MultivariateNormal as mvn
from torch.distributions.one_hot_categorical import OneHotCategorical as cat
from torch.distributions.gamma import Gamma
from torch import logsumexp

def kls_step(x, z, q_mean, q_nu, q_alpha, q_beta, q_pi, prior_mean, prior_nu, prior_alpha, prior_beta, prior_pi, mus, precisions, N, K, D, batch_size):
    p_mean, p_nu, p_alpha, p_beta = post_global(x, z, prior_mean, prior_nu, prior_alpha, prior_beta, N, K, D)
    kl_eta_ex, kl_eta_in = kls_NGs(p_mean, p_nu, p_alpha, p_beta, q_mean, q_nu, q_alpha, q_beta)
    p_logits = post_local(x, prior_pi, mus, precisions, N, K, D, batch_size)
    kl_z_ex, kl_z_in = kls_cats(p_logits, torch.log(q_pi))
    return kl_eta_ex, kl_eta_in, kl_z_ex, kl_z_in

def kl_normal_normal(p_mean, p_std, q_mean, q_std):
    var_ratio = (p_std / q_std).pow(2)
    t1 = ((p_mean - q_mean) / q_std).pow(2)
    return 0.5 * (var_ratio + t1 - 1 - var_ratio.log())

def kls_gaussians(mus_mean, mus_sigma, posterior_mean, posterior_sigma):
    Kl_exclusive = kl_normal_normal(mus_mean, mus_sigma, posterior_mean, posterior_sigma).sum(-1).sum(-1).mean()
    Kl_inclusive = kl_normal_normal(posterior_mean, posterior_sigma, mus_mean, mus_sigma).sum(-1).sum(-1).mean()
    return Kl_exclusive, Kl_inclusive

def kl_gamma_gamma(p_alpha, p_beta, q_alpha, q_beta):
    t1 = q_alpha * (p_beta / q_beta).log()
    t2 = torch.lgamma(q_alpha) - torch.lgamma(p_alpha)
    t3 = (p_alpha - q_alpha) * torch.digamma(p_alpha)
    t4 = (q_beta - p_beta) * (p_alpha / p_beta)
    return t1 + t2 + t3 + t4

def kls_gammas(precsions_alpha, precisions_beta, posterior_alpha, posterior_beta):
    KL_exclusive = kl_gamma_gamma(precsions_alpha, precisions_beta, posterior_alpha, posterior_beta).sum(-1).sum(-1).mean()
    KL_inclusive = kl_gamma_gamma(posterior_alpha, posterior_beta, precsions_alpha, precisions_beta).sum(-1).sum(-1).mean()
    return KL_exclusive, KL_inclusive

def kl_NG_NG(p_mean, p_nu, p_alpha, p_beta, q_mean, q_nu, q_alpha, q_beta):
    diff = q_mean - p_mean
    t1 = (1. / 2) * ((p_alpha / p_beta) *  (diff ** 2) * q_nu + (q_nu / p_nu) - (torch.log(q_nu) - torch.log(p_nu)) - 1)
    t2 = q_alpha * (torch.log(p_beta) - torch.log(q_beta)) - (torch.lgamma(p_alpha) - torch.lgamma(q_alpha)) 
    t3 = (p_alpha - q_alpha) * torch.digamma(p_alpha) - (p_beta - q_beta) * p_alpha / p_beta
    return t1 + t2 + t3

def kls_NGs(p_mean, p_nu, p_alpha, p_beta, q_mean, q_nu, q_alpha, q_beta):
    kl_exclusive = kl_NG_NG(q_mean, q_nu, q_alpha, q_beta, p_mean, p_nu, p_alpha, p_beta).sum(-1).sum(-1)
    kl_inclusive = kl_NG_NG(p_mean, p_nu, p_alpha, p_beta, q_mean, q_nu, q_alpha, q_beta).sum(-1).sum(-1)
    return kl_exclusive, kl_inclusive


def kl_cat_cat(p_logits, q_logits, EPS=1e-8):
    p_probs = torch.exp(p_logits)
    q_probs = torch.exp(q_logits) + EPS
    t = p_probs * (p_logits - q_logits)
    # t[(q_probs == 0).expand_as(t)] = inf
    t[(p_probs == 0).expand_as(t)] = 0
    return t.sum(-1)

def kls_cats(p_logits, q_logits, EPS=1e-8):
    KL_ex = kl_cat_cat(q_logits, p_logits + EPS).sum(-1)
    KL_in = kl_cat_cat(p_logits, q_logits + EPS).sum(-1)
    return KL_ex, KL_in

def post_global(Xs, Zs, prior_mean, prior_nu, prior_alpha, prior_beta, N, K, D):
    Zs_fflat = Zs.unsqueeze(-1).repeat(1, 1, 1, 1, D)
    Xs_fflat = Xs.unsqueeze(-1).repeat(1, 1, 1, 1, K).transpose(-1, -2)
    stat1 = Zs.sum(2).unsqueeze(-1).repeat(1, 1, 1, D) ## S * B * K * D
    xz_nk = torch.mul(Zs_fflat, Xs_fflat) # S*B*N*K*D
    stat2 = xz_nk.sum(2) ## S*B*K*D
    stat3 = torch.mul(Zs_fflat, torch.mul(Xs_fflat, Xs_fflat)).sum(2) # S*B*K*D
    stat1_nonzero = stat1
    stat1_nonzero[stat1_nonzero == 0.0] = 1.0
    x_bar = stat2 / stat1
    posterior_beta = prior_beta + (stat3 - (stat2 ** 2) / stat1_nonzero) / 2. + (stat1 * prior_nu / (stat1 + prior_nu)) * ((prior_nu**2) + x_bar**2 - 2 * x_bar *  prior_nu) / 2.
    posterior_nu = prior_nu + stat1
    posterior_mean = (prior_mean * prior_nu + stat2) / (prior_nu + stat1) 
    posterior_alpha = prior_alpha + (stat1 / 2.)
#     posterior_sigma = torch.sqrt(posterior_nu * (posterior_beta / posterior_alpha))
    return posterior_mean, posterior_nu, posterior_alpha, posterior_beta

def post_local(Xs, Pi, mus, precisions, N, K, D, batch_size):
    sigmas = 1. / torch.sqrt(precisions)
    mus_expand = mus.unsqueeze(-2).repeat(1, 1, 1, N, 1) # S * B * K * N * D
    sigmas_expand = sigmas.unsqueeze(-2).repeat(1, 1, 1, N, 1) # S * B * K * N * D
    Xs_expand = Xs.unsqueeze(2).repeat(1, 1, K, 1, 1) #  S * B * K * N * D
    log_gammas = Normal(mus_expand, sigmas_expand).log_prob(Xs_expand).sum(-1).transpose(-1, -2) # S * B * N * K
    log_pis = log_gammas - logsumexp(log_gammas, dim=-1).unsqueeze(-1)
    return log_pis