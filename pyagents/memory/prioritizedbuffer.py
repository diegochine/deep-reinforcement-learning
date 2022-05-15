import numpy as np
import gin
from collections import deque
from pyagents.memory.buffer import Buffer
from pyagents.memory.sum_tree import SumTree


@gin.configurable
class PrioritizedBuffer(Buffer):

    def __init__(self,
                 save_dir=None,
                 size=100000,
                 n_step_return=1,
                 eps=0.02,
                 alpha=0.6,
                 beta=(0.0, 1.0, 10 ** 6)):
        super().__init__(save_dir)
        self._sum_tree = SumTree(size)
        self._size = size
        self._n = n_step_return - 1
        self._stmemory = deque(maxlen=self._n)
        self._ltmemory = dict()
        self._ptr = 0
        self._eps = eps
        self._alpha = alpha
        if isinstance(beta, int):
            self._beta = beta
            self._beta_max = beta
            self._beta_inc = 0
        elif isinstance(beta, tuple):
            self._beta, self._beta_max, steps = beta
            self._beta_inc = (self._beta_max - self._beta) / steps
        self._config = {'size': size, 'n_step_return': n_step_return,
                        'eps_buffer': eps, 'alpha': alpha, 'beta': self._beta,
                        'beta_max': self._beta_max, 'beta_inc': self._beta_inc}

    def __len__(self):
        return len(self._sum_tree)

    @property
    def n_step_return(self):
        return self._n + 1

    def get_config(self):
        return self._config

    def commit_stmemory(self, fragment: np.array, gamma: float = 0.99):
        """Stores a new experience fragment in the buffer.

        Args:
            fragment:
            gamma: discount factor
        """
        states, actions, rewards, next_states, dones = fragment
        batch_size = states.shape[0]  # first dim is input batch size, i.e. n_envs
        st_experience = {'state': states, 'actions': actions, 'reward': rewards, 'next_state': next_states, 'dones': dones}
        if 1 < self._n == len(self._stmemory):  # time to compute truncated multi step return
            for b in range(batch_size):
                s_t = self._stmemory[0]['states'][b]
                a_t = self._stmemory[0]['actions'][b]
                r_tpn = 0
                for k, e_k in enumerate(self._stmemory):
                    r_tpn += (gamma ** k) * e_k['rewards'][b]
                    if e_k['dones'][b]:
                        break
                s_tpn = e_k['next_states']
                done_tpn = e_k['dones'][b]
                lt_experience = {'state': s_t, 'action': a_t, 'reward': r_tpn, 'next_state': s_tpn, 'done': done_tpn}
                self.commit_ltmemory(lt_experience)
            self.stmemory.append(st_experience)
        else:
            for b in range(batch_size):
                lt_experience = {'state': states[b],
                                 'action': actions[b],
                                 'reward': rewards[b],
                                 'next_state': next_states[b],
                                 'done': dones[b]}
                self.commit_ltmemory(lt_experience)

    def commit_ltmemory(self, experience):
        self._ltmemory[self._ptr] = experience
        self._sum_tree.set(self._ptr)  # mark as new experience in sum tree
        self._ptr = (self._ptr + 1) % self._size

    def clear_stmemory(self):
        self.stmemory.clear()

    def sample(self, batch_size, vectorizing_fn=lambda x: x):
        bounds = np.linspace(0., 1., batch_size + 1)
        indexes = [self._sum_tree.sample(lb=bounds[i], ub=bounds[i + 1]) for i in range(batch_size)]
        priorities = np.array([self._sum_tree.get(idx) for idx in indexes]) + self._eps
        samples = [tuple(self._ltmemory[idx].values()) for idx in indexes]
        if self._beta != 0:
            priorities_pow = np.power(priorities, self._alpha)
            probs = priorities_pow / priorities_pow.sum()
            is_weights = np.power(1/(len(self._sum_tree) * probs), self._beta)
            is_weights = is_weights / np.max(is_weights)
        else:
            is_weights = np.ones_like(indexes)
        self._beta = min(self._beta + self._beta_inc, self._beta_max)
        return vectorizing_fn(samples), indexes, is_weights

    def update_samples(self, errors, indexes):
        assert len(errors.shape) == 1 and errors.shape[0] == len(indexes)
        for error_idx, mem_idx in enumerate(indexes):
            self._sum_tree.set(mem_idx, errors[error_idx].numpy())
