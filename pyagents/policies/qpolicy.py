import numpy as np
import tensorflow as tf
from pyagents.policies.policy import Policy


class QPolicy(Policy):

    def __init__(self, state_shape, action_shape, q_network):
        super().__init__(state_shape, action_shape)
        self._q_network = q_network

    def _act(self, obs, mask=None, training=True):
        qvals = self._q_network(obs.reshape(1, *obs.shape))
        if mask is not None:
            assert isinstance(mask, np.ndarray)
            qvals = tf.where(mask, qvals, np.NINF)
        return np.argmax(qvals, keepdims=True)[0]

    def _distribution(self, obs):
        qvals = self._q_network(obs.reshape(1, *obs.shape))
        return qvals / tf.reduce_sum(qvals)
