import time
import numpy as np
import torch
import matplotlib.pyplot as plt

from unityagents import UnityEnvironment

from get_args import get_args
from agent import DQN_Agent
from agent_utils import train


def main():
    """
    Primary code for training or testing an agent using one of several
    optional network types. Deep Q-Network, Double DQN, etcself.

    This is a project designed for Udacity's Deep Reinforcement Learning Nanodegree
    and uses a special version of Unity's Banana learning environment. This
    environment should be available via the github repository at:
    https://github.com/whiterabbitobj/udacity-deep-reinforcement-learning/tree/master/p1_navigation

    Example command:
    python banana_deeprl.py -mode train -a DDQN --epsilon .9 --epsilon_decay .978
    """

    #Get start time
    start_time = time.time()


    args = get_args()

    #if the user has not chosen a mode, quit early and print an error
    if args.mode is None:
        print("ERROR: Please choose a mode in which to run the agent.")
        return

    #send all the training to the GPU, if available
    device = torch.device("cuda:0" if torch.cuda.is_available() and not args.cpu else "cpu")

    #initialize the environment
    unity_env = UnityEnvironment(file_name="Banana_Windows_x86_64/Banana.exe", no_graphics=args.nographics)

    # get the default brain (In this environment there is only one agent/brain)
    brain_name = unity_env.brain_names[0]
    brain = unity_env.brains[brain_name]
    env = unity_env.reset(train_mode=True)[brain_name]

    action_size = brain.vector_action_space_size
    state_size = len(env.vector_observations[0])

    #choose how often to average the score & print training data. This value is
    #bounded between 2 and 100.
    args.print_count = min(max(int(args.num_episodes/args.print_count),2), 100)

    if args.debug:
        print_debug_info(device, action_size, state_size, env, args)


    # THIS IS WHERE WE NEED TO IMPLEMENT DIFFERENT AGENT TYPES, THE CODE TO
    # *RUN* THE AGENT IS UNIFORM ACROSS AGENT TYPES!
    agent = DQN_Agent(state_size, action_size, device, args, seed=0)


    #TRAIN the agent
    if args.mode == "train":
        print("Printing training data every {} episodes.\n{}".format(args.print_count,"#"*50))
        scores = train(unity_env, agent, args, brain_name)
        plot_scores(scores)


    #TEST the agent
    # save_name = "checkpoint_" + model.name + time.strftime("_%Y_%m_%d_%Hh%Mm%Ss", time.gmtime()) + ".pth"
    # if os.path.isdir(in_args.save_dir):
    #     save_name = os.path.join(in_args.save_dir, save_name)
    #
    # print("Saving to: ", save_name)
    # save_checkpoint(model, save_name)

    # if np.mean(scores_window)>=200.0:
    #     print('\nEnvironment solved in {:d} episodes!\tAverage Score: {:.2f}'.format(i_episode-100, np.mean(scores_window)))
    #     torch.save(agent.qnetwork_local.state_dict(), 'checkpoint.pth')
    #     break


    print("TOTAL RUNTIME: {:.1f} seconds".format(time.time()-start_time))
    unity_env.close()



    return

def plot_scores(scores):
    fig = plt.figure()
    ax = fig.add_subplot(111)
    plt.plot(np.arange(len(scores)), scores)
    plt.ylabel('Score')
    plt.xlabel('Episode #')
    plt.show()
    return

if __name__ == "__main__":
    main()
