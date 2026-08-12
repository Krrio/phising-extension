# GuardianClassic Crew

Welcome to the GuardianClassic Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the dependencies:

(Optional) Lock the dependencies and install them by using the CLI command:
```bash
crewai install
```
### Customizing

**Add your `OPENAI_API_KEY` into the `.env` file**

- Modify `src/guardian_classic/config/agents.yaml` to define your agents
- Modify `src/guardian_classic/config/tasks.yaml` to define your tasks
- Modify `src/guardian_classic/crew.py` to add your own logic, tools and specific args
- Modify `src/guardian_classic/main.py` to add custom inputs for your agents and tasks

## Running the Project

To kickstart your crew of AI agents and begin task execution, run this from the root folder of your project:

```bash
$ crewai run
```

This command initializes the guardian_classic Crew, assembling the agents and assigning them tasks as defined in your configuration.

This example, unmodified, will run the create a `report.md` file with the output of a research on LLMs in the root folder.

## Domain registration cache

The domain-age tool asks RDAP first and uses WHOIS only when the registry does
not expose a usable registration date. Successful lookups and short-lived
negative results are stored in SQLite at `.cache/registration_cache.db`.
Override that path with `GUARDIAN_CACHE_DB=/path/to/cache.db`.

The cache stores only the normalized registrable domain, registration timestamp,
source, status and cache metadata; complete RDAP/WHOIS responses are not stored.
Expired entries are pruned periodically, and LRU eviction keeps the cache below
50,000 domains and keeps the complete SQLite file below 64 MiB. Maintenance
runs at startup, at most once every six hours, or after 1,000 cache writes, so
no separate cleanup process is required. The `.cache/` directory is
intentionally ignored by Git.

## Understanding Your Crew

The guardian_classic Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the GuardianClassic Crew or crewAI.
- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
