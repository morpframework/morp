from ..app import App
from morpfw.crud.storage.memorystorage import MemoryStorage
from ..user.model import UserModel, UserSchema, UserCollection
from ..group.model import GroupModel, GroupSchema, GroupCollection
from ..apikey.model import APIKeyModel, APIKeySchema
from .interfaces import IUserStorage, IGroupStorage
from morpfw.crud import errors as cruderrors
from .. import exc
import rulez

DB: dict = {"users": {}, "groups": {}, "rolemap": {}}


class UserMemoryStorage(MemoryStorage, IUserStorage):
    model = UserModel

    def get_userid(self, model):
        return model.uuid

    def get_by_email(self, collection, email):
        users = self.search(collection, rulez.field["email"] == email)
        if not users:
            return None
        return users[0]

    def get_by_userid(self, collection, userid):
        users = self.search(collection, rulez.field["uuid"] == userid)
        if not users:
            return None
        return users[0]

    def get_by_username(self, collection, username):
        users = self.search(collection, rulez.field["username"] == username)
        if not users:
            return None
        return users[0]

    def change_password(self, collection, userid, new_password):
        user = self.get_by_userid(collection, userid)
        user.data["password"] = new_password

    def get_user_groups(self, collection, userid):
        storage = self.request.app.get_storage(GroupModel, self.request)
        gcol = GroupCollection(self.request, storage)
        return storage.get_user_groups(userid, gcol)

    def validate(self, collection, userid, password):
        user = self.get_by_userid(collection, userid)
        return user.data["password"] == password


class APIKeyMemoryStorage(MemoryStorage):
    model = APIKeyModel


class GroupMemoryStorage(MemoryStorage, IGroupStorage):
    model = GroupModel

    def get_user_by_userid(self, collection, userid, as_model=True):
        user_storage = self.app.get_storage(UserModel, self.request)
        user_collection = UserCollection(self.request, user_storage)
        return user_storage.get_by_userid(user_collection, userid, as_model)

    def get_user_by_username(self, collection, username, as_model=True):
        user_storage = self.app.get_storage(UserModel, self.request)
        user_collection = UserCollection(self.request, user_storage)
        return user_storage.get(user_collection, username)

    def get_user_groups(self, userid, collection):
        res = []
        for gid, group in self.datastore.items():
            if userid in group.data["xattrs"].get("members"):
                res.append(group)
        return res

    def get_members(self, groupname, collection):
        group = self.get(groupname, collection)
        userstorage = self.request.app.get_storage(UserModel, self.request)
        usercol = UserCollection(self.request, userstorage)
        res = []
        group.data.setdefault("xattrs", {})
        attrs = group.data["xattrs"]
        attrs.setdefault("members", [])
        for m in group.data["xattrs"].get("members"):
            res.append(userstorage.get_by_userid(usercol, m))
        return res

    def add_group_members(self, collection, groupname, userids):
        group = self.get(collection, groupname)
        group.data.setdefault("xattrs", {})
        attrs = group.data["xattrs"]
        attrs.setdefault("members", [])
        for u in userids:
            if u not in attrs["members"]:
                attrs["members"].append(u)
        group.data["xattrs"] = attrs

    def remove_group_members(self, collection, groupname, userids):
        group = self.get(collection, groupname)
        group.data.setdefault("xattrs", {})
        attrs = group.data["xattrs"]
        attrs.setdefault("members", [])
        for u in userids:
            if u in attrs["members"]:
                attrs["members"].remove(u)
        group.data["xattrs"] = attrs

    def get_group_user_roles(self, collection, groupname, userid):
        rolemap = DB["rolemap"]
        rolemap.setdefault(groupname, {})
        rolemap[groupname].setdefault(userid, [])
        return rolemap[groupname][userid]

    def grant_group_user_role(self, collection, groupname, userid, rolename):
        rolemap = DB["rolemap"]
        rolemap.setdefault(groupname, {})
        rolemap[groupname].setdefault(userid, [])
        if rolename not in rolemap[groupname][userid]:
            rolemap[groupname][userid].append(rolename)

    def revoke_group_user_role(self, collection, groupname, userid, rolename):
        rolemap = DB["rolemap"]
        rolemap.setdefault(groupname, {})
        rolemap[groupname].setdefault(userid, [])
        if rolename in rolemap[groupname][userid]:
            rolemap[groupname][userid].remove(rolename)


SINGLETON: dict = {}
