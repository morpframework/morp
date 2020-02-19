import datetime
from dataclasses import _MISSING_TYPE

from dateutil.parser import parse as parse_date

from ...interfaces import IDataProvider, ISchema
from ..app import App
from ..schemaconverter.common import dataclass_check_type, dataclass_get_type
from ..schemaconverter.dataclass2colanderjson import dataclass_to_colanderjson
from ..storage.memorystorage import MemoryStorage
from ..types import datestr

_MARKER: list = []


class DictProvider(IDataProvider):
    def __init__(self, schema, data, storage):
        self.schema = schema
        self.data = data
        self.storage = storage
        self.changed = False

    def __getitem__(self, key):
        t = dataclass_check_type(
            self.schema.__dataclass_fields__[key], datetime.datetime
        )
        if t:
            data = self.data[key]
            if isinstance(data, str):
                return parse_date(data)
            return data
        if key not in self.data.keys():
            field = self.schema.__dataclass_fields__[key]
            if field.default is not _MISSING_TYPE:
                return field.default
            if field.default_factory is not _MISSING_TYPE:
                return field.default_factory()
            return None
        return self.data[key]

    def __setitem__(self, key, value):
        field = self.schema.__dataclass_fields__[key]
        t = dataclass_get_type(field)
        for v in t["metadata"]["validators"]:
            v(key, value)
        if t["type"] == datetime.datetime:
            if value and not isinstance(value, datetime.datetime):
                value = parse_date(value)
        self.data[key] = value
        self.changed = True

    def __delitem__(self, key):
        del self.data[key]
        self.changed = True

    def setdefault(self, key, value):
        field = self.schema.__dataclass_fields__[key]
        t = dataclass_get_type(field)
        for v in t["metadata"]["validators"]:
            v(value)
        r = self.data.setdefault(key, value)
        self.changed = True
        return r

    def get(self, key, default=_MARKER):
        if default is _MARKER:
            return self.data.get(key)
        return self.data.get(key, default)

    def set(self, key, value):
        field = self.schema.__dataclass_fields__[key]
        t = dataclass_get_type(field)
        for v in t["metadata"]["validators"]:
            v(value)
        self.data[key] = value
        self.changed = True

    def items(self):
        return self.data.items()

    def keys(self):
        return self.data.keys()

    def as_dict(self):
        result = {}
        for k, v in self.data.items():
            result[k] = v
        return result

    def as_json(self):
        cschema = dataclass_to_colanderjson(self.schema, self.storage.request)
        return cschema().serialize(self.as_dict())


@App.dataprovider(schema=ISchema, obj=dict, storage=MemoryStorage)
def get_dataprovider(schema, obj, storage):
    return DictProvider(schema, obj, storage)


@App.jsonprovider(obj=DictProvider)
def get_jsonprovider(obj):
    return obj.as_json()
