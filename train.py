import os
import random

import numpy as np
import gym
from argparse import ArgumentParser

import wandb

from pyagents.agents import DQNAgent, VPG, A2C, DDPG
from pyagents.layers import RescalingLayer
from pyagents.networks import DiscreteQNetwork, PolicyNetwork, ValueNetwork, SharedBackboneACNetwork, ACNetwork
from pyagents.memory import PrioritizedBuffer, UniformBuffer
import tensorflow as tf
from tensorflow.keras.optimizers import Adam
import gin


@gin.configurable
def train_dqn_agent(test_ver, n_episodes=1000, batch_size=128, learning_rate=0.001, steps_to_train=4, buffer='uniform',
                    episode_max_steps=500, min_memories=30000, output_dir="./output/", wandb_params=None):
    is_testing = (test_ver >= 0)
    env = gym.make('CartPole-v1')
    state_size = env.observation_space.shape[0]
    action_size = env.action_space.n

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    buffer = PrioritizedBuffer() if buffer == 'prioritized' else UniformBuffer()
    q_net = DiscreteQNetwork(state_size, action_size)
    optim = Adam(learning_rate=learning_rate)
    if not is_testing:
        player = DQNAgent(state_size, action_size, q_network=q_net, buffer=buffer, optimizer=optim,
                          name='dqn', wandb_params=wandb_params,
                          log_dict={'learning_rate': learning_rate})
    else:
        player = DQNAgent.load('output/dqn', ver=test_ver, epsilon=0.01, training=False)
    if player.is_logging:
        wandb.define_metric('score', step_metric="episode", summary="max")
    scores = []
    movavg100 = []
    eps_history = []
    player.memory_init(env, episode_max_steps, min_memories)

    for episode in range(1, n_episodes + 1):  # TODO switch to training_steps

        s_t = env.reset()
        s_t = np.reshape(s_t, player.state_shape)
        step = 0
        done = False

        while not done and step < episode_max_steps:
            if is_testing:
                env.render()
            a_t = player.act(s_t)
            s_tp1, r_t, done, info = env.step(a_t)
            r_t = r_t if not done else -100
            s_tp1 = np.reshape(s_tp1, player.state_shape)
            player.remember(state=s_t, action=a_t, reward=r_t, next_state=s_tp1, done=done)
            s_t = s_tp1

            if not is_testing and step % steps_to_train == 0:
                losses = player.train(batch_size)
            step += 1

        scores.append(step)
        this_episode_score = np.mean(scores[-100:])
        movavg100.append(this_episode_score)
        eps_history.append(player.get_policy().epsilon)
        print(f'EPISODE: {episode:4d}/{n_episodes:4d}, '
              f'SCORE: {this_episode_score:3.0f}, '
              f'LOSS: {losses["td_loss"]:3.2f}',
              f'EPS: {player.get_policy().epsilon:.2f}')

        if player.is_logging:
            wandb.log({'score': scores[-1], 'episode': episode, 'eps': player.get_policy().epsilon})

        player.train(batch_size)

        if (episode % 10) == 0:
            player.save(ver=episode // 10)

    return scores, movavg100, eps_history


@gin.configurable
def train_vpg_agent(test_ver, n_episodes=1000, episode_max_steps=250,
                    actor_learning_rate=1e-4, critic_learning_rate=1e-3, schedule=True,
                    output_dir="./output/", wandb_params=None):
    is_testing = (test_ver >= 0)
    env = gym.make('CartPole-v1')
    state_size = env.observation_space.shape[0]
    action_size = (env.action_space.n,)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    a_net = PolicyNetwork(state_size, action_size,
                          output='softmax',
                          fc_params=(16, 16),
                          dropout_params=0.1)
    v_net = ValueNetwork(state_size, fc_params=(16, 16), dropout_params=0.1)
    if schedule:
        a_lr = tf.keras.optimizers.schedules.PolynomialDecay(actor_learning_rate, n_episodes, actor_learning_rate / 100)
        c_lr = tf.keras.optimizers.schedules.PolynomialDecay(critic_learning_rate, n_episodes,
                                                             critic_learning_rate / 100)
    else:
        a_lr = actor_learning_rate
        c_lr = critic_learning_rate
    a_opt = Adam(learning_rate=a_lr)
    v_opt = Adam(learning_rate=c_lr)
    if not is_testing:
        player = VPG(state_size, action_size,
                     actor=a_net, critic=v_net, actor_opt=a_opt, critic_opt=v_opt,
                     name='vpg', wandb_params=wandb_params,
                     log_dict={'actor_learning_rate': actor_learning_rate,
                               'critic_learning_rate': critic_learning_rate})
    else:
        player = VPG.load('output/vpg', ver=test_ver, epsilon=0.01, training=False)
    if player.is_logging:
        wandb.define_metric('score', step_metric="episode", summary="max")
    scores = []
    movavg100 = []

    for episode in range(1, n_episodes + 1):  # TODO switch to training_steps

        s_t = env.reset()
        s_t = np.reshape(s_t, player.state_shape)
        step = 0
        score = 0
        done = False

        while not done and step < episode_max_steps:
            if is_testing:
                env.render()
            a_t = player.act(s_t)
            s_tp1, r_t, done, info = env.step(a_t)
            r_t = r_t if not done else -10
            s_tp1 = np.reshape(s_tp1, player.state_shape)
            player.remember(state=s_t, action=a_t, reward=r_t)
            s_t = s_tp1
            step += 1
            score += r_t
        if not is_testing:
            losses = player.train()

        if player.is_logging:
            wandb.log({'score': step, 'episode': episode})
        scores.append(step)
        this_episode_score = np.mean(scores[-100:])
        movavg100.append(this_episode_score)

        log_str = f'EPISODE: {episode:4d}/{n_episodes:4d}, SCORE: {this_episode_score:3.0f}'
        if not is_testing:
            log_str += f',POLICY LOSS: {losses["policy_loss"]:4.2f}, CRITIC LOSS: {losses["critic_loss"]:5.2f}'
        print(log_str)

        if (episode % 10) == 0:
            player.save(ver=episode//10)

    return scores, movavg100


@gin.configurable
def train_a2c_agent(env, test_ver, total_training_steps=10**5, episode_max_steps=250,
                    learning_rate=1e-3, schedule=True, batch_size=64,
                    output_dir="./output/", wandb_params=None):
    is_testing = (test_ver >= 0)
    state_shape = env.observation_space.shape
    action_shape = (env.action_space.n,)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ac_net = SharedBackboneACNetwork(state_shape, action_shape, distribution='softmax')
    if schedule:
        lr = tf.keras.optimizers.schedules.PolynomialDecay(learning_rate, total_training_steps, learning_rate / 100)
    else:
        lr = learning_rate
    opt = Adam(learning_rate=lr)
    if not is_testing:
        player = A2C(state_shape, action_shape, actor_critic=ac_net, opt=opt,
                     name='a2c', wandb_params=wandb_params,
                     log_dict={'actor_learning_rate': learning_rate, 'critic_learning_rate': learning_rate})
    else:
        player = A2C.load('output/a2c', ver=test_ver, training=False)
    if player.is_logging:
        wandb.define_metric('score', step_metric="episode", summary="max")
    scores = []
    movavg100 = []
    episode = 0
    training_step = 0

    while training_step <= total_training_steps:
        episode += 1
        s_t = env.reset()
        s_t = np.reshape(s_t, player.state_shape)
        episode_step = 0
        score = 0
        done = False
        losses = None

        while not done and episode_step < episode_max_steps:
            if is_testing or True:
                env.render()
            a_t = player.act(s_t)
            s_tp1, r_t, done, info = env.step(a_t)
            r_t = r_t if not done else -(200 - episode_step)/10
            s_tp1 = np.reshape(s_tp1, player.state_shape)
            player.remember(state=s_t, action=a_t, reward=r_t, next_state=s_tp1, done=done)
            s_t = s_tp1
            episode_step += 1
            score += r_t
            if not is_testing:
                # TODO in "what matters for on policy rl" dicono che è importante usare la stessa traiettoria per più updates
                loss_info = player.train(batch_size)
                training_step += 1
                losses = loss_info if loss_info is not None else losses

        scores.append(episode_step)
        this_episode_score = np.mean(scores[-100:])
        movavg100.append(this_episode_score)
        if player.is_logging:
            wandb.log({'score': episode_step, 'episode': episode})
        if not is_testing and losses is not None:
            loss_str = f', POLICY LOSS: {losses["policy_loss"]:4.2f}, ' \
                       f'CRITIC LOSS: {losses["critic_loss"]:4.2f}, ' \
                       f'ENTROPY LOSS: {losses["entropy_loss"]:4.2f}'
        else:
            loss_str = ''
        print(f'STEP: {training_step:4d}/{total_training_steps:4d}, SCORE: {this_episode_score:3.0f}' + loss_str)

        if (episode % 10) == 0:
            player.save(ver=episode//10)

    return scores, movavg100


@gin.configurable
def train_ddpg_agent(test_ver, total_training_steps=10**5, scaling=2.0,
                     batch_size=128, a_learning_rate=5e-4, c_learning_rate=1e-3, train_every=25,
                     episode_max_steps=250, min_memories=50000, output_dir="./output/", wandb_params=None):
    is_testing = (test_ver >= 0)
    env = gym.make('Pendulum-v1')
    state_size = env.observation_space.shape
    action_size = env.action_space.shape
    bounds = (env.action_space.low, env.action_space.high)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    buffer = UniformBuffer()
    pi_params = {'bounds': bounds,
                 'out_params': {'activation': 'tanh'}}
    if scaling is not None:
        pi_params['action_processing_layer'] = RescalingLayer(scaling_factor=scaling)
    q_params = {}
    ac = ACNetwork(state_shape=state_size, action_shape=action_size,
                   pi_out='continuous', pi_params=pi_params, q_params=q_params)
    a_opt = Adam(learning_rate=a_learning_rate)
    c_opt = Adam(learning_rate=c_learning_rate)
    if not is_testing:
        player = DDPG(state_size, action_size, actor_critic=ac, buffer=buffer, actor_opt=a_opt, critic_opt=c_opt,
                      action_bounds=bounds, name='ddpg', wandb_params=wandb_params,
                      log_dict={'actor_learning_rate': a_learning_rate,
                                'critic_learning_rate': c_learning_rate})
        player.memory_init(env, episode_max_steps, min_memories)
    else:
        player = DDPG.load('output/ddpg', ver=test_ver, training=False)
    if player.is_logging:
        wandb.define_metric('score', step_metric="episode", summary="max")
    scores = []
    movavg100 = []
    pi_losses = []
    q_losses = []
    episode = 0
    training_step = 0

    while training_step <= total_training_steps:
        episode += 1
        s_t = env.reset()
        s_t = np.reshape(s_t, player.state_shape)
        episode_step = 0
        score = 0
        done = False

        while not done and episode_step < episode_max_steps:
            if is_testing:
                env.render()
            a_t = player.act(s_t.reshape(1, -1))[0]
            s_tp1, r_t, done, info = env.step(a_t)
            s_tp1 = np.reshape(s_tp1, player.state_shape)
            player.remember(state=s_t, action=a_t, reward=r_t, next_state=s_tp1, done=done)
            s_t = s_tp1

            if not is_testing and training_step % train_every == 0:
                for _ in range(train_every):
                    losses = player.train(batch_size)
                    pi_losses.append(losses['policy_loss'])
                    q_losses.append(losses['critic_loss'])
            episode_step += 1
            score += r_t

        scores.append(score)
        movavg_score = np.mean(scores[-100:])
        movavg100.append(movavg_score)
        print(f'EPISODE: {episode:4d}/{total_training_steps:4d}, '
              f'SCORE: {scores[-1]:5.0f} (MOVAVG {movavg_score:5.0f}), '
              f'POLICY LOSS: {np.mean(pi_losses):3.2f}, ',
              f'Q LOSS: {np.mean(q_losses):3.2f}')
        pi_losses = []
        q_losses = []

        if player.is_logging:
            wandb.log({'score': scores[-1], 'episode': episode})

        if not is_testing:
            player.train(batch_size)
            if (episode % 10) == 0:
                player.save(ver=episode // 10)
            training_step += 1

    return scores, movavg100


def reset_random_seed(seed):
    os.environ['PYTHONHASHSEED'] = str(seed)
    tf.random.set_seed(seed)
    np.random.seed(seed)
    random.seed(seed)


if __name__ == "__main__":
    parser = ArgumentParser(description="Script for training a sample agent on Gym")
    parser.add_argument('-a', '--agent', type=str, help='which agent to use, either DQN, VPG, A2C or DDPG')
    parser.add_argument('-c', '--config', type=str, default='', help='path to gin config file')
    parser.add_argument('-tv', '--test-ver', type=int, default=-1,
                        help='if -1, trains; if >=0, performs evaluation using this version')
    args = parser.parse_args()
    env = gym.make('CartPole-v1')
    env = gym.wrappers.NormalizeObservation(env)  # TODO update all training functions to accept env from outside
    if args.config:
        gin.parse_config_file(args.config)
    if args.agent == 'dqn':
        info = train_dqn_agent(test_ver=args.test_ver)
    elif args.agent == 'vpg':
        info = train_vpg_agent(test_ver=args.test_ver)
    elif args.agent == 'a2c':
        info = train_a2c_agent(env=env, test_ver=args.test_ver)
    elif args.agent == 'ddpg':
        info = train_ddpg_agent(test_ver=args.test_ver)
    else:
        raise ValueError(f'wrong agent {args.agent}')
