__all__ = ["sloted"]

class sloted(object):
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
