import gin
import tensorflow as tf
from pyagents.networks.network import Network
from pyagents.networks.encoding_network import EncodingNetwork
from pyagents.layers import GaussianLayer, DirichletLayer
from pyagents.policies import GaussianPolicy, DirichletPolicy


@gin.configurable
class ActorNetwork(Network):

    def __init__(self, state_shape, action_shape, distribution='beta', preprocessing_layers=None,
                 conv_layer_params=None, fc_layer_params=(64, 64), dropout_params=None, activation='relu',
                 name='ActorNetwork', trainable=True, dtype=tf.float32):
        super(ActorNetwork, self).__init__(name, trainable, dtype)
        self._config = {'state_shape': state_shape,
                        'action_shape': action_shape,
                        'preprocessing_layers': [lay.get_config() for lay in preprocessing_layers]
                        if preprocessing_layers else [],
                        'conv_layer_params': conv_layer_params if conv_layer_params else [],
                        'fc_layer_params': fc_layer_params if fc_layer_params else [],
                        'dropout_params': dropout_params if dropout_params else [],
                        'activation': activation,
                        'name': name}
        if dropout_params is None:
            dropout_params = [None] * len(fc_layer_params)
        self._encoder = EncodingNetwork(
            state_shape,
            preprocessing_layers=preprocessing_layers,
            conv_layer_params=conv_layer_params,
            fc_layer_params=fc_layer_params,
            dropout_params=dropout_params,
            activation=activation,
            name=name
        )
        self._out_distribution = distribution
        if distribution == 'gaussian':
            self._out_layer = GaussianLayer(state_shape, action_shape)
        elif distribution == 'beta':
            self._out_layer = DirichletLayer(state_shape, action_shape)

    @property
    def policy(self):
        if self._out_distribution == 'gaussian':
            return GaussianPolicy(self._config['state_shape'], self._config['action_shape'], self)
        elif self._out_distribution == 'beta':
            return DirichletPolicy(self._config['state_shape'], self._config['action_shape'], self, bounds=(-2, 2)) # TODO improve this hardcoded bounds

    def call(self, inputs, training=True, mask=None):
        state = self._encoder(inputs, training=training)
        dist_params = self._out_layer(state, training=training)
        return dist_params

