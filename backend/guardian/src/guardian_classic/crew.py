from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from guardian_classic.tools.suspicious_domain_tool import SuspiciousDomainTool
from guardian_classic.models import GuardianVerdict
from guardian_classic.tools.domain_age_tool import DomainAgeTool


@CrewBase
class GuardianClassic():
    """GuardianClassic crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def orkiestrator(self) -> Agent:
        return Agent(
            config=self.agents_config['orkiestrator'],
            verbose=False
        )

    @agent
    def analityk_domen(self) -> Agent:
        return Agent(
            config=self.agents_config['analityk_domen'],
            tools=[SuspiciousDomainTool(), DomainAgeTool()],
            verbose=False
        )

    @agent
    def analityk_tresci(self) -> Agent:
        return Agent(
            config=self.agents_config['analityk_tresci'],
            verbose=False
        )

    @task
    def badanie_domen_task(self) -> Task:
        return Task(
            config=self.tasks_config['badanie_domen_task'],
        )

    @task
    def analiza_tresci_task(self) -> Task:
        return Task(
            config=self.tasks_config['analiza_tresci_task'],
        )

    @task
    def synteza_task(self) -> Task:
        return Task(
            config=self.tasks_config['synteza_task'],
            output_pydantic=GuardianVerdict,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the GuardianClassic crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
