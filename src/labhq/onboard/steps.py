"""The steps labhq ships with. A new step (Discord, for one) registers here from its module."""

from labhq.onboard.channels import ChannelsStep
from labhq.onboard.connector import ConnectorTokenStep
from labhq.onboard.database import DatabaseStep
from labhq.onboard.discord import DiscordStep
from labhq.onboard.model import ModelLoginStep
from labhq.onboard.notifications import NotificationsStep
from labhq.onboard.public_url import PublicUrlStep
from labhq.onboard.registry import StepRegistry

default_steps = StepRegistry()
default_steps.register(DatabaseStep(), order=10)
default_steps.register(ConnectorTokenStep(), order=20)
default_steps.register(PublicUrlStep(), order=30)
default_steps.register(NotificationsStep(), order=40)
default_steps.register(ChannelsStep(), order=45)
default_steps.register(ModelLoginStep(), order=50)
default_steps.register(DiscordStep(), order=60)
