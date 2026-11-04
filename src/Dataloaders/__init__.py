from uoishelpers.dataloaders.LoaderMapBase import LoaderMapBase
from uoishelpers.dataloaders.IDLoader import IDLoader

import src.DBDefinitions
from src.DBDefinitions import BaseDBModel, EventModel, EventInvitationModel, TagTypeModel, TagModel, TagEntityModel


class LoaderMap(LoaderMapBase[BaseDBModel]):
    BaseModel = BaseDBModel

    EventModel: IDLoader[src.DBDefinitions.EventModel] = None
    EventInvitationModel: IDLoader[src.DBDefinitions.EventInvitationModel] = None
    TagTypeModel: IDLoader[src.DBDefinitions.TagTypeModel] = None
    TagModel: IDLoader[src.DBDefinitions.TagModel] = None
    TagEntityModel: IDLoader[src.DBDefinitions.TagEntityModel] = None

    def __init__(self, session):
        super().__init__(session)
        self.EventModel = self.get(EventModel)
        self.EventInvitationModel = self.get(EventInvitationModel)
        self.TagTypeModel = self.get(TagTypeModel)
        self.TagModel = self.get(TagModel)
        self.TagEntityModel = self.get(TagEntityModel)

    def get_by_name(self, name: str):
        return getattr(self, name)


def createLoadersContext(session):
    """Compatibility helper for places expecting a dict context."""
    return {'loaders': LoaderMap(session)}
