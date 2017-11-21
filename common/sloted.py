__all__ = ["sloted"]

from .reflection import get_class_total_args
from inspect import getmro

class sloted(object):
    __slots__ = ["__dfs_visited__"]

    def __init__(self, **kw):
        for klass in type(self).__mro__:
            try:
                slots = klass.__slots__
            except AttributeError:
                continue

            for attr in slots:
                if attr.startswith("_"):
                    continue
                setattr(self, attr, kw[attr])

    def gen_by_slots(self, gen, **extra):
        """ Helper for implementation of __gen_code__ for PyGenerator API. """
        self_type = type(self)

        slots2gen = []
        for klass in getmro(self_type):
            try:
                slots = klass.__slots__
            except AttributeError:
                continue

            for attr in reversed(slots):
                if attr.startswith("_"):
                    continue
                if attr in slots2gen:
                    continue
                slots2gen.append(attr)

        _, defaults = get_class_total_args(self_type)

        gen.reset_gen(self)

        for attr in reversed(slots2gen):
            val = getattr(self, attr)

            if (attr in defaults) and (defaults[attr] == val):
                continue

            gen.gen_field(attr + " = ")
            gen.pprint(val)

        for k, val in extra.items():
            if (k in defaults) and (defaults[k] == val):
                continue

            gen.gen_field(k + " = ")
            gen.pprint(val)

        gen.gen_end()
