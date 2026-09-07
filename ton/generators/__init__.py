"""Built-in value generators (Strategy pattern).

Each module here implements one generator class that:

* declares the ``type`` discriminator it handles in :attr:`type_name`,
* knows nothing about templates, configs, or rows -- it only turns a
  spec mapping plus a ``random.Random`` into a string value,
* may opt into the *paired* role by subclassing :class:`PairedGenerator`
  to emit both a primary value and a secondary (``[id]``) value within
  the same row.

The :mod:`ton.registry` module collects these classes into a name -> instance
mapping that the engine uses to dispatch. To add a new built-in type:

1. Create ``<type>.py`` with a ``<Type>Generator(Generator)`` subclass
   (or ``PairedGenerator`` if you need the paired contract).
2. Export it from this ``__init__``.
3. Add it to ``BUILTIN_GENERATOR_CLASSES`` below.

Third-party generators do not need to live here -- they can be registered
via the ``ton.generators`` entry-point group.
"""

from .base import Generator, PairedGenerator
from .boolean import BooleanGenerator
from .bytes import BytesGenerator
from .char import CharGenerator
from .date import DateGenerator
from .decimal import DecimalGenerator
from .hash import HashGenerator
from .identity import EmailGenerator, NameGenerator, PhoneGenerator
from .integer import IntegerGenerator
from .network import IPv4Generator, IPv6Generator, MACGenerator
from .one_of import OneOfGenerator
from .regex import RegexGenerator
from .sequence import SequenceGenerator
from .sequence_of import SequenceOfGenerator
from .string import StringGenerator
from .text import TextGenerator
from .timestamp_unix import TimestampUnixGenerator
from .uuid import UUIDGenerator
from .weighted import WeightedGenerator

#: Canonical built-in generator classes. Used as the allowlist for
#: ``ton._registry.make_registry`` so in-process test fixtures or
#: third-party subclasses (which still appear in
#: ``Generator.__subclasses__()``) do not leak into the default registry
#: (ARCH-005).
BUILTIN_GENERATOR_CLASSES: tuple[type[Generator], ...] = (
    BooleanGenerator,
    BytesGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    EmailGenerator,
    HashGenerator,
    IPv4Generator,
    IPv6Generator,
    IntegerGenerator,
    MACGenerator,
    NameGenerator,
    OneOfGenerator,
    PhoneGenerator,
    RegexGenerator,
    SequenceGenerator,
    SequenceOfGenerator,
    StringGenerator,
    TextGenerator,
    TimestampUnixGenerator,
    UUIDGenerator,
    WeightedGenerator,
)

BUILTIN_GENERATOR_CONFIG_KEYS: dict[str, frozenset[str]] = {
    "boolean": frozenset(("whenTrue", "whenFalse")),
    "bytes": frozenset(("length", "encoding")),
    "char": frozenset(("values", "maxChar")),
    "date": frozenset(("minValue", "maxValue", "format")),
    "decimal": frozenset(("minValue", "maxValue", "decimals", "padWithZero")),
    "email": frozenset(("domains",)),
    "hash": frozenset(("values", "algorithm", "rounds", "cache")),
    "ipv4": frozenset(("cidr",)),
    "ipv6": frozenset(("cidr",)),
    "integer": frozenset(("minValue", "maxValue", "padWithZero")),
    "mac": frozenset(("separator", "uppercase", "oui")),
    "name": frozenset(("style",)),
    "oneOf": frozenset(("choices",)),
    "phone": frozenset(("format",)),
    "regex": frozenset(("pattern",)),
    "sequence": frozenset(("start", "step", "padWidth")),
    "sequence_of": frozenset(("count", "separator", "spec")),
    "string": frozenset(("values",)),
    "text": frozenset(("unit", "count")),
    "timestamp_unix": frozenset(("minValue", "maxValue", "unit")),
    "uuid": frozenset(("version", "uppercase")),
    "weighted": frozenset(("values", "weights", "choices")),
}
for _generator_class in BUILTIN_GENERATOR_CLASSES:
    _generator_class.config_keys = BUILTIN_GENERATOR_CONFIG_KEYS[_generator_class.type_name]

__all__ = [
    "BUILTIN_GENERATOR_CLASSES",
    "BUILTIN_GENERATOR_CONFIG_KEYS",
    "BooleanGenerator",
    "BytesGenerator",
    "CharGenerator",
    "DateGenerator",
    "DecimalGenerator",
    "EmailGenerator",
    "Generator",
    "HashGenerator",
    "IPv4Generator",
    "IPv6Generator",
    "IntegerGenerator",
    "MACGenerator",
    "NameGenerator",
    "OneOfGenerator",
    "PairedGenerator",
    "PhoneGenerator",
    "RegexGenerator",
    "SequenceGenerator",
    "SequenceOfGenerator",
    "StringGenerator",
    "TextGenerator",
    "TimestampUnixGenerator",
    "UUIDGenerator",
    "WeightedGenerator",
]
