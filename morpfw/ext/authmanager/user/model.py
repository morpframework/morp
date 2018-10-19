from morpfw.jslcrud import Collection, Model, StateMachine
from morpfw.jslcrud import errors as cruderrors
from .storage import User
from ..app import App
import jsl
from .. import exc
import sqlalchemy as sa
import sqlalchemy_jsonfield as sajson
from ..model import NAME_PATTERN, EMAIL_PATTERN
from morpfw.jslcrud import signals as crudsignal
from morpfw.jslcrud import errors as cruderrors
from morpfw.jslcrud.model import Schema
from morpfw.jslcrud.validator import regex_validator
from ..group.model import GroupCollection, GroupSchema
from uuid import uuid4
import re
import jsonobject


class RegistrationSchema(jsonobject.JsonObject):
    # pattern=NAME_PATTERN)
    username = jsonobject.StringProperty(
        required=True, validators=[regex_validator(NAME_PATTERN, 'name')])
    # pattern=EMAIL_PATTERN
    email = jsonobject.StringProperty(required=True, validators=[
                                      regex_validator(EMAIL_PATTERN, 'email')])
    password = jsonobject.StringProperty(required=True)
    password_validate = jsonobject.StringProperty(required=True, default='')


class LoginSchema(jsonobject.JsonObject):

    username = jsonobject.StringProperty(required=True)
    password = jsonobject.StringProperty(required=True)


class UserSchema(Schema):

    username = jsonobject.StringProperty(
        required=True, validators=[regex_validator(NAME_PATTERN, 'name')])  # , pattern=NAME_PATTERN)
    # , pattern=EMAIL_PATTERN)
    email = jsonobject.StringProperty(required=True, validators=[
                                      regex_validator(EMAIL_PATTERN, 'email')])
    password = jsonobject.StringProperty(required=False)
    groups = jsonobject.ListProperty(
        str, required=False)  # pattern=NAME_PATTERN
    attrs = jsonobject.DictProperty(required=False)
    state = jsonobject.StringProperty(required=False)
    created = jsonobject.StringProperty(required=False)
    modified = jsonobject.StringProperty(required=False)
    nonce = jsonobject.StringProperty(required=False)


@App.jslcrud_identifierfields(schema=UserSchema)
def user_identifierfields(schema):
    return ['username']


class UserCollection(Collection):
    schema = UserSchema

    def authenticate(self, username, password):
        if re.match(EMAIL_PATTERN, username):
            user = self.storage.get_by_email(username)
            if user is None:
                return False
            return user.validate(password)

        user = self.storage.get(username)
        if user is None:
            return False
        return user.validate(password)

    def _create(self, data):
        data['nonce'] = uuid4().hex
        exists = self.storage.get(data['username'])
        if exists:
            raise exc.UserExistsError(data['username'])
        return super(UserCollection, self)._create(data)


class UserModel(Model):

    schema = UserSchema

    def change_password(self, password, new_password):
        if not self.app.authmanager_has_role(self.request, 'administrator'):
            if not self.validate(password, check_state=False):
                raise exc.InvalidPasswordError(self.data['username'])
        self.storage.change_password(self.data['username'], new_password)

    def validate(self, password, check_state=True):
        if check_state and self.data['state'] != 'active':
            return False
        return self.storage.validate(self.data['username'], password)

    def groups(self):
        return self.storage.get_user_groups(self.data['username'])

    def group_roles(self):
        group_roles = {}
        for g in self.groups():
            group_roles[g.data['groupname']] = g.get_member_roles(
                self.data['username'])
        return group_roles


class UserStateMachine(StateMachine):

    states = ['active', 'inactive', 'deleted']
    transitions = [
        {'trigger': 'activate', 'source': 'inactive', 'dest': 'active'},
        {'trigger': 'deactivate', 'source': 'active', 'dest': 'inactive'},
        {'trigger': 'delete', 'source': [
            'active', 'inactive'], 'dest': 'deleted'}
    ]

    def on_enter_deleted(self):
        self._context.delete()


@App.jslcrud_statemachine(model=UserModel)
def userstatemachine(context):
    return UserStateMachine(context)


@App.jslcrud_jsontransfrom(schema=UserSchema)
def jsontransform(request, context, data):
    data = data.copy()
    for f in ['password', 'password_validate']:
        if f in data.keys():
            del data[f]
    data['groups'] = [g.identifier for g in context.groups()]
    return data


@App.jslcrud_subscribe(signal=crudsignal.OBJECT_CREATED, model=UserModel)
def add_user_to_default_group(app, request, obj, signal):
    request = obj.request
    storage = app.get_authmanager_storage(request, GroupSchema)
    g = storage.get('__default__')
    if g is None:
        gcol = GroupCollection(request, storage)
        g = gcol.create({'groupname': '__default__'})
    g.add_members([obj.data['username']])
