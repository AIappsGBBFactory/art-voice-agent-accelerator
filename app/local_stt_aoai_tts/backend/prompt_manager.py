import os
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from utils.ml_logging import get_logger

logger = get_logger()

class PromptManager:
    def __init__(self, template_dir: str = "templates"):
        """
        Initialize the PromptManager with the given template directory.

        Args:
            template_dir (str): The directory containing the Jinja2 templates.
        """
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, template_dir)

        self.env = Environment(
            loader=FileSystemLoader(searchpath=template_path), autoescape=False
        )

        templates = self.env.list_templates()
        print(f"Templates found: {templates}")

    def get_prompt(self, template_name: str, **kwargs) -> str:
        """
        Render a template with the given context.

        Args:
            template_name (str): The name of the template file.
            **kwargs: The context variables to render the template with.

        Returns:
            str: The rendered template as a string.
        """
        try:
            template = self.env.get_template(template_name)
            return template.render(**kwargs)
        except Exception as e:
            raise ValueError(f"Error rendering template '{template_name}': {e}")

    def create_prompt_system_voice_agent(
        self,
    ) -> str:
        """
        Create a user prompt for evaluating policy search results.

        Args:
            query (str): The user's query regarding prior authorization (e.g. "What is
                         the prior authorization policy for Epidiolex for LGS?")
            search_results (List[Dict[str, Any]]): A list of retrieved policies, each containing:
                - 'id': Unique identifier
                - 'path': URL or file path
                - 'content': Extracted policy text
                - 'caption': Summary or short description

        Returns:
            str: The rendered prompt (evaluator_user_prompt.jinja) instructing how to
                 evaluate these policies against the query, deduplicate, and form
                 a final JSON-like response.
        """
        return self.get_prompt(
            "app/backend/prompts/voice_agent_system.jinja",
            query=query,
            SearchResults=search_results,
        )
