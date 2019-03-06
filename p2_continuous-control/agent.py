import numpy as np
import copy
# import random
from collections import namedtuple, deque
from progressbar import ProgressBar
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from buffers import ReplayBuffer
from models import ActorNet, CriticNet


class D4PG_Agent: #(Base_Agent):
    def __init__(self,
                 state_size,
                 action_size,
                 agent_count,
                 a_lr = 1e-4,
                 c_lr = 1e-4,
                 batch_size = 128,
                 buffer_size = 1000000,
                 C = 1000,
                 gamma = 0.99,
                 tau = 0.0005,
                 rollout = 5,
                 weight_decay = 0.0001):
        """
        Implementation of D4PG:
        "Distributed Distributional Deterministic Policy Gradients"
        As described in the paper at: https://arxiv.org/pdf/1804.08617.pdf

        Much thanks also to the original DDPG paper:
        https://arxiv.org/pdf/1509.02971.pdf

        And to the work of Bellemare et al:
        "A Distributional Perspective on Reinforcement Learning"
        https://arxiv.org/pdf/1707.06887.pdf

        D4PG utilizes distributional value estimation, n-step returns,
        prioritized experience replay (PER), distributed K-actor exploration,
        and off-policy actor-critic learning to achieve very fast and stable
        learning for continuous control tasks.

        This version of the Agent is written to interact with Udacity's
        Continuous Control robotic arm manipulation environment which provides
        20 simultaneous actors, negating the need for K-actor implementation.
        Thus, this code has no multiprocessing functionality.

        In the original D4PG paper, it is suggested in the data that PER does
        not have significant (or perhaps any at all) effect on the speed or
        stability of learning. Thus, it too has been left out of this
        implementation but may be added as a future TODO item.
        """

        self.framework = "D4PG"
        self.t_step = 0
        self.episode = 0
        self.batch_size = batch_size
        self.C = C
        self.e = .3
        self.e_decay = 0.99999
        self.state_size = state_size
        self.action_size = action_size
        self.agent_count = agent_count
        self.rollout = rollout
        self.gamma = gamma
        self.tau = tau

        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        # Set up memory buffers, one for Replay Buffer and one to handle
        # collecting data for n-step returns
        self.memory = ReplayBuffer(buffer_size)

        # Initialize ACTOR networks
        self.actor = ActorNet(state_size, action_size).to(self.device)
        self.actor_target = copy.deepcopy(self.actor).to(self.device)
        self.actor_optim = optim.Adam(self.actor.parameters(), lr=a_lr)

        # Initialize CRITIC networks
        self.critic = CriticNet(state_size, action_size).to(self.device)
        self.critic_target = copy.deepcopy(self.critic).to(self.device)
        self.critic_optim = optim.Adam(self.critic.parameters(), lr=c_lr, weight_decay=weight_decay)
        #self.critic_loss = nn.CrossEntropyLoss()

        self.new_episode()


    def new_episode(self):
        """
        Handle any cleanup or steps to begin a new episode of training.
        """
        self._reset_nstep_memory()
        self.episode += 1

    def initialize_memory(self, pretrain_length, env):
        """
        Fills up the ReplayBuffer memory with PRETRAIN_LENGTH number of experiences
        before training begins.
        """
        if len(self.memory) >= pretrain_length:
            print("Memory already filled, length: {}".format(len(self.memory)))
            return

        print("Initializing memory buffer.")
        states = env.states
        while len(self.memory) < pretrain_length:
            actions = np.random.uniform(-1, 1, (self.agent_count, self.action_size))
            next_states, rewards, dones = env.step(actions)
            self.step(states, actions, rewards, next_states, pretrain=True)
            print("Taking pretrain step... {}, memory filled: {}/{}".format(self.t_step, len(self.memory), pretrain_length))

            states = next_states
        print("Done!")
        self.t_step = 0

    def act(self, states):
        states = states.to(self.device)
        actions = self.actor(states).detach().cpu()
        actions = actions.numpy() #.astype(np.float32)
        noise = self._gauss_noise(actions.shape)
        actions += noise
        actions = np.clip(actions, -1, 1)
        return actions

    def step(self, states, actions, rewards, next_states, pretrain=False):
        # Current SARS' stored in short term memory, then stacked for NStep
        memory = list(zip(states, actions, rewards, next_states))
        self._store_memories(memory)

        self.t_step += 1

        if pretrain:
            return

        self._learn()
        self.e *= self.e_decay

    def _store_memories(self, experiences):
        """
        Once the n_step_memory holds ROLLOUT number of sars' tuples, then a full
        memory can be added to the ReplayBuffer.
        """
        self.n_step_memory.append(experiences)

        # Abort if ROLLOUT steps haven't been taken in a new episode
        if len(self.n_step_memory) < self.rollout:
            return

        # Unpacks and stores the SARS' tuple for each actor in the environment
        # thus, each timestep actually adds K_ACTORS memories to the buffer,
        # for the Udacity environment this means 20 memories each timestep.
        for actor in zip(*self.n_step_memory):
            states, actions, rewards, next_states = zip(*actor)
            n_steps = self.rollout - 1
            rewards = np.fromiter((rewards[i] * self.gamma**i for i in range(n_steps)), float, count=n_steps)
            rewards = rewards.sum()
            #print("Rewards:", rewards)
            # store the current state, current action, cumulative discounted
            # reward from t -> t+n-1, and the next_state at t+n (S't+n)
            states = states[0].unsqueeze(0)
            actions = torch.from_numpy(actions[0]).unsqueeze(0).double()
            rewards = torch.tensor([rewards])
            next_states = next_states[-1].unsqueeze(0)
            self.memory.store(states, actions, rewards, next_states)

    def _learn(self):
        batch = self.memory.sample(self.batch_size)
        #states, actions, rewards, next_states = batch
        states = torch.cat(batch.state).to(self.device)
        actions = torch.cat(batch.action).float().to(self.device)
        rewards = torch.cat(batch.reward).to(self.device)
        next_states = torch.cat(batch.next_state).to(self.device)

        # Calculate Yᵢ from target networks using θ' and W'
        target_dist = self._get_targets(rewards, next_states).detach()
        # Calculate value distribution for current state using weights W
        predicted_dist, log_probs = self.critic(states, actions)
        critic_loss = -(target_dist * log_probs).sum(-1).mean()
        #print("target_dist: {}   log_probs: {}".format(target_dist, log_probs))
        # print((target_dist * log_probs).sum(-1))
        # print((target_dist * log_probs).sum())
        #critic_loss = nn.CrossEntropyLoss(predicted_dist, target)
        #critic_loss = self.critic_loss(current_value_dist, target)

        # Predict action for actor network loss calculation using θ
        predicted_action = self.actor(states)
        expected_reward, _ = self.critic(states, predicted_action)
        actor_loss = -(expected_reward).mean()
        # actor_loss = expected_reward.mean()

        #print("Critic Loss: {}   Actor Loss: {}:".format(critic_loss, actor_loss))
        # Perform gradient descent
        self.actor_optim.zero_grad()
        actor_loss.backward()
        self.actor_optim.step()

        self.critic_optim.zero_grad()
        critic_loss.backward()
        self.critic_optim.step()

        ### Soft-update like in original DDPG
        self._soft_update(self.critic_target, self.critic)
        self._soft_update(self.actor_target, self.actor)

        ## Hard update as in DQN and implied by D4PG paper
        # if  self.t_step % self.C == 0:
        #     self.critic_target.load_state_dict(self.critic.state_dict())
        #     self.actor_target.load_state_dict(self.actor.state_dict())

    def _categorical(self,
                    rewards,
                    probs,
                    vmin = 0,
                    vmax = 1,
                    num_atoms = 51):
        """
        Returns the projected value distribution for the input state/action pair
        """

        rewards = rewards.unsqueeze(-1)
        atoms = torch.linspace(vmin, vmax, num_atoms).to(self.device)
        delta_z = (vmax - vmin) / (num_atoms - 1)

        projected_atoms = rewards + self.gamma**self.rollout * atoms.view(1,-1)
        projected_atoms.clamp_(vmin, vmax)
        b = (projected_atoms - vmin) / delta_z

        lower_bound = b.floor()
        upper_bound = b.ceil()

        m_lower = (upper_bound + (lower_bound == upper_bound).float() - b) * probs
        m_upper = (b - lower_bound) * probs

        projected_probs = torch.tensor(np.zeros(probs.size())).to(self.device)
        for idx in range(probs.size(0)):
            projected_probs[idx].index_add_(0, lower_bound[idx].long(), m_lower[idx].double())
            projected_probs[idx].index_add_(0, upper_bound[idx].long(), m_lower[idx].double())

        return projected_probs.float()

    def _soft_update(self, target, active):
        for t_param, param in zip(target.parameters(), active.parameters()):
            t_param.data.copy_(self.tau*param.data + (1-self.tau)*t_param.data)

    def _get_targets(self, rewards, next_states):
        target_actions = self.actor_target(next_states)#.detach()
        target_probs, t_logs = self.critic_target(next_states, target_actions)#.detach()
        #print("target_probs: {}   t_log_probs: {}".format(target_probs[0], t_logs[0]))
        projected_probs = self._categorical(rewards, target_probs)
        #return rewards + projected_probs
        return projected_probs

    def _gauss_noise(self, shape):
        n = np.random.normal(0, 1, shape)
        return self.e*n

    def _reset_nstep_memory(self):
        """
        Creates (or recreates to zero an existing) deque to handle nstep returns.
        """
        self.n_step_memory = deque(maxlen=self.rollout)
