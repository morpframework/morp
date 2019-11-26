from ..app import App
from .model import UserCollection, UserModel
from ....crud.rulesprovider.base import RulesProvider
from ..utils import has_role
from .. import exc


class UserRulesProvider(RulesProvider):

    context: UserModel

    def change_password(self, password: str, new_password: str):
        context = self.context
        if not has_role(self.request, 'administrator'):
            if not context.validate(password, check_state=False):
                raise exc.InvalidPasswordError(context.userid)
        context.storage.change_password(
            context.identity.userid, new_password)

    def validate(self, password: str, check_state=True) -> bool:
        context = self.context
        if check_state and context.data['state'] != 'active':
            return False
        return context.storage.validate(context.userid, password)


@App.rulesprovider(model=UserModel)
def get_user_rulesprovider(context):
    return UserRulesProvider(context)