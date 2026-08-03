# Decisions (as noted by me, the dev)

I've vetted and agree with everything from [DECISIONS_AGENT.md](DECISIONS_AGENT.md), but wanted to just give a bit more informal context on top of it.

## Overview

1. I wanted to start with the data generation, making sure that our TMS data was fleshed out in such a way that it covered our edge-cases and talking points we wanted to hit during our demo. So we started there, with the data

2. Once we made several iterations on our data generation script and felt satisfied, we moved on to some high-level planning of our carrier-ranking algorithm. We wanted to use industry knowledge + first principles as our primary reasoning engine, but we also knew that we were constrained by the shape of the TMS data that we were receiving from our brokers. Because of this, we started with a simple set of weighted rules around a few primary attributes: empty miles 30%, lane experience 24%, price 16%, on-time record 12%, relationship depth 10%, customer history 4%, rate and fall-through stability 4%.

3. Lots of backend testing was introduced during the first 2 steps above, and this is when we continued on to add considerations for our shared carrier-pool feature. We continued testing and iterating until our backend data and algorithm felt stable.

4. We then proceeded to build the platform. The stack was less important, but we ultimately decided to pull in the shadcn MCP + the /frontend-design skill from claude to help us get some baseline sanity with our design direction. We made many iterations in pursuit of clarity and correctness. Even with confidence in our data, we didn't want to misrepresent that data or the insights that the data gave us. I spent a lot of time trying to get a UX that would be reasonably clear for a broker to understand at a glance.

5. We than conducted several rounds of full-app audits to look for holes in correctness, integrity, or reasoning. We found many holes and violations of our originally-provided constraints along the way and made sure to patch them as early and often as we could so we could stay grounded in correctness.

6. The last round of development went to organizing our md files in preparation for a code-review and/or live demo.

## Judgement Calls & Trade-offs

I placed a lot of trust in my coding agent (mostly Opus 5 - High) to collaborate with me on the technical thinking here. I knew the general direction I wanted to go, but I also knew there would be many nuances and questions that I wouldn't reasonably uncover myself alone in the amount of time I had. Because of this, I leaned heavily on conversation & collaborative planning sessions (of which I preserved in the "/agent plans" folder in our project). Due to this workflow, I've left a large number of the decisions we made for the agent to remember in our documentation (see DECISIONS_AGENT.md).

I'll speak now to the few key trade-offs that stuck with me to this moment and are at top-of-mind:

1. How do we balance a proven carrier whom has a lot of deadhead (ie. empty miles) before it reaches the pickup location, against a carrier who is much closer to the pickup location but has very little or very poor history? The answer: we decided that deadhead must be harshly punished (it is the most heavily weighted attribute in our ranking algorithm), but also that a poor history (high percentage of late deliveries, etc.) would not be easily forgiven either. The result is that a reliable carrier A with proven lane experience can still be ranked above a less reliable carrier B, even if that reliable carrier A has a considerable amount of empty miles ahead of them to reach the location. Ultimately, we surface these metrics to the broker so that they can make the final judgement.

2. In our shared carrier pool, what data should or shouldn't we surface. Initially I made a decision that if the active broker already had history for a carrier, that then had additional data surface in the shared carrier pool, that the additional data would be ignored to continue only relying on the active brokers history with that carrier. After some experiementation, I realized that this was less than optimal, because if we could use that additional data to give a clearer picture about that carrier's equipment resources and where they are currently located, then we could give a more accurate take on how many empty miles would be needed for that carrier to reach the pickup location. This is our most important metric, so I decided to rollback my initial decision and to begin sharing the trip/lane history of the shared carriers as well. However, I limited that to facts about the *carrier* — where their trucks have been seen, what equipment they run, whether they show up on time — and never facts about a broker's own book. Broker rates, margins, customers and load records all remain private.

## If I had more time

I'd focus on the priority list layed out in [DECISIONS_AGENT.md](DECISIONS_AGENT.md) first and foremost, and then beyond that I would:

1. pull the shared carrier-pool opt-in toggle out of the dev menu and put it somewhere within the app where a broker could toggle it themselves. This requires more time for UI/UX reasoning, and I didn't feel it necessary for the purposes of this project.

2. Create a larger, more realistic dataset that could emulate what we might have in a production environemnt after 1 year of real use. Use this to do additional testing and optimize our algorithm attributes, weights and biases further.

3. Investigate if there's anything I could do to get a higher resolution stream of data from our customers and their TMS systems.

## If I had more time AND higher resolution TMS data

1. source a more robust dataset for our geographic map, and track our carrier progress to the highest resolution possible. Do this to improve frontend UX and clarity, but also to help make our carrier-ranking algorithm more sophisticated.

2. Look for other opportunities to extract useful patterns in the TMS data to surface actionable insights for our users, the brokers.
