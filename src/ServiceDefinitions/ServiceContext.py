import dataclasses
import typing

from src.Dataloaders import LoaderMap

if typing.TYPE_CHECKING:
    from src.ServiceDefinitions.Domain_Events.EventService import EventService as _EventService
    from src.ServiceDefinitions.Domain_Events.EventInvitationService import EventInvitationService as _EventInvitationService
    from src.ServiceDefinitions.Domain_Tags.TagTypeService import TagTypeService as _TagTypeService
    from src.ServiceDefinitions.Domain_Tags.TagService import TagService as _TagService
    from src.ServiceDefinitions.Domain_Tags.TagEntityService import TagEntityService as _TagEntityService


@dataclasses.dataclass(frozen=True)
class ServiceRegistry:
    @property
    def EventService(self) -> type['_EventService']:
        from src.ServiceDefinitions.Domain_Events.EventService import EventService
        return EventService

    @property
    def EventInvitationService(self) -> type['_EventInvitationService']:
        from src.ServiceDefinitions.Domain_Events.EventInvitationService import EventInvitationService
        return EventInvitationService

    @property
    def TagTypeService(self) -> type['_TagTypeService']:
        from src.ServiceDefinitions.Domain_Tags.TagTypeService import TagTypeService
        return TagTypeService

    @property
    def TagService(self) -> type['_TagService']:
        from src.ServiceDefinitions.Domain_Tags.TagService import TagService
        return TagService

    @property
    def TagEntityService(self) -> type['_TagEntityService']:
        from src.ServiceDefinitions.Domain_Tags.TagEntityService import TagEntityService
        return TagEntityService


SERVICES = ServiceRegistry()


@dataclasses.dataclass
class ServiceContext:
    loaders: LoaderMap
    user: typing.Any = None
    ug_client: typing.Callable[..., typing.Awaitable[typing.Any]] | None = None
    request: typing.Any = None
    session: typing.Any = None
    Services: ServiceRegistry = SERVICES

    # uoishelpers helpers commonly expect info.context to behave like a dict
    # with at least the key "loaders". Keeping these methods lets us pass a
    # typed ServiceContext directly as Strawberry context.
    def __getitem__(self, key: str) -> typing.Any:
        return getattr(self, key)

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)
