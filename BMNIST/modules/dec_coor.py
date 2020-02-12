import torch
import torch.nn as nn
from torch.distributions.normal import Normal
import probtorch

class Dec_coor():
    """
    Real generative model for time dynamics
    z_1 ~ N (0, Sigma_0) : S * B * D
    z_t | z_t-1 ~ N (A z_t-1, Sigma_t)
    where A is the transformation matrix
    """
    def __init__(self, z_where_dim, CUDA, DEVICE):
        super(self.__class__, self)

        self.prior_mu0 = torch.zeros(z_where_dim)
        self.prior_Sigma0 = torch.ones(z_where_dim) * 1.0
        self.prior_Sigmat = torch.ones(z_where_dim) * 0.2
        if CUDA:
            with torch.cuda.device(DEVICE):
                self.prior_mu0  = self.prior_mu0.cuda()
                self.prior_Sigma0 = self.prior_Sigma0.cuda()
                self.prior_Sigmat = self.prior_Sigmat.cuda()
        # self.prior_Sigmat = nn.Parameter(self.prior_Sigmat)
    def forward(self, z_where_t, z_where_t_1=None, disp=None):
        S, B, D = z_where_t.shape
        if z_where_t_1 is None:
            p0 = Normal(self.prior_mu0, self.prior_Sigma0)
            return p0.log_prob(z_where_t).sum(-1)# S * B
        else:
            p0 = Normal(z_where_t_1, self.prior_Sigmat)
            return p0.log_prob(z_where_t).sum(-1) # S * B

    def log_prior(self, z_where_t, z_where_t_1=None, disp=None):
        S, B, K, D = z_where_t.shape
        if z_where_t_1 is None:
            p0 = Normal(self.prior_mu0, self.prior_Sigma0)
            return p0.log_prob(z_where_t).sum(-1).sum(-1)#)# S * B
        else:
            p0 = Normal(z_where_t_1, self.prior_Sigmat)
            return p0.log_prob(z_where_t).sum(-1).sum(-1)# # S * B
