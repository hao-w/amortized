import torch
from torch.distributions.normal import Normal
from torch.distributions.one_hot_categorical import OneHotCategorical as cat
from torch.distributions.categorical import Categorical
from torch.distributions.uniform import Uniform
import math
import numpy as np

def shuffler(data):
    DIM1, DIM2, DIM3 = data.shape
    indices = torch.cat([torch.randperm(DIM2).unsqueeze(0) for b in range(DIM1)])
    indices_expand = indices.unsqueeze(-1).repeat(1, 1, DIM3)
    return torch.gather(data, 1, indices_expand)

def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        m.weight.data.normal_(0.0, 1e-3)

def Resample(var, weights, idw_flag=True):
    dim1, dim2, dim3, dim4 = var.shape
    if idw_flag:
        if dim2 == 1:
            ancesters = Categorical(weights.permute(1, 2, 0).squeeze(0)).sample((dim1, )).unsqueeze(1).unsqueeze(-1).repeat(1, 1, 1, dim4)
        else:
            ancesters = Categorical(weights.permute(1, 2, 0)).sample((dim1, )).unsqueeze(-1).repeat(1, 1, 1, dim4)
    else:
        ancesters = Categorical(weights.transpose(0, 1)).sample((dim1, )).unsqueeze(-1).unsqueeze(-1).repeat(1, 1, dim3, dim4) ## S * B * N * K
    return torch.gather(var, 0, ancesters)

def True_decoder(ob, state, angle, mu, recon_sigma, idw_flag=False):
    """
    cluster_flag = False : return S * B * N
    cluster_flag = True, return S * B * K
    """
    labels = state.argmax(-1)
    labels_expand = labels.unsqueeze(-1).repeat(1, 1, 1, mu.shape[-1])
    mu_expand = torch.gather(mu, -2, labels_expand)
    recon_mu = torch.cat((torch.cos(angle), torch.sin(angle)), -1) * 2.0 + mu_expand
    ll = Normal(recon_mu, recon_sigma).log_prob(ob).sum(-1)
    if idw_flag:
        ll = torch.cat([((labels==k).float() * ll).sum(-1).unsqueeze(-1) for k in range(state.shape[-1])], -1) # S * B * K
    return ll

def global_to_local(var, state):
    """
    var is global variable of size S * B * K * D
    state is cluster assignment of size S * B * N * K
    """
    D = var.shape[-1]
    labels = state.argmax(-1).unsqueeze(-1).repeat(1, 1, 1, D)
    var_expand = torch.gather(var, -2, labels)
    return var_expand

def ss_to_stats(ss, state):
    """
    ss :  S * B * N * D
    state : S * B * N * K

    """
    D = ss.shape[-1]
    K = state.shape[-1]
    state_expand = state.unsqueeze(-1).repeat(1, 1, 1, 1, D)
    ss_expand = ss.unsqueeze(-1).repeat(1, 1, 1, 1, K).transpose(-1, -2)
    nss = (state_expand * ss_expand).sum(2) / (state_expand.sum(2) + 1e-6)
    return nss

def sample_ancestral_index(weights, DEVICE):
    batch_size, num_particles = weights.size()
    indices = np.zeros([batch_size, num_particles])

    uniforms = np.random.uniform(size=[batch_size, 1])
    pos = (uniforms + np.arange(0, num_particles)) / num_particles

    normalized_weights = weights.cpu().data.numpy()

    # np.ndarray [batch_size, num_particles]
    cumulative_weights = np.cumsum(normalized_weights, axis=1)

    # hack to prevent numerical issues
    cumulative_weights = cumulative_weights / np.max(
        cumulative_weights, axis=1, keepdims=True)
    for batch in range(batch_size):
        indices[batch] = np.digitize(pos[batch], cumulative_weights[batch])
    return torch.from_numpy(indices).long().cuda().to(DEVICE)


def S_Resample(var, weights, DEVICE, idw_flag=True):
    S, B, dim3, dim4 = var.shape
    if idw_flag :
        indices = sample_ancestral_index(weights.view(S, B*dim3).transpose(0,1), DEVICE)
        ancesters = indices.transpose(0,1).view(S, B, dim3).unsqueeze(-1).repeat(1, 1, 1, dim4)
    else:
        indices = sample_ancestral_index(weights.transpose(0,1), DEVICE) # B * S or B * S * N
        ancesters = indices.transpose(0,1).unsqueeze(-1).unsqueeze(-1).repeat(1, 1, dim3, dim4)
    return torch.gather(var, 0, ancesters)
