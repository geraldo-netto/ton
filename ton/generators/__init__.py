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
3. Add it to ``default_registry()`` in :mod:`ton.registry`.

Third-party generators do not need to live here -- they can be registered
via the ``ton.generators`` entry-point group.
"""

from .base import Generator, PairedGenerator
from .boolean import BooleanGenerator
from .bytes import BytesGenerator
from .char import CharGenerator
from .date import DateGenerator
from .decimal import DecimalGenerator
from .identity import EmailGenerator, NameGenerator, PhoneGenerator
from .integer import IntegerGenerator
from .lmhash import LMHashGenerator
from .network import IPv4Generator, IPv6Generator, MACGenerator
from .regex import RegexGenerator
from .sequence import SequenceGenerator
from .string import StringGenerator
from .text import TextGenerator
from .timestamp_unix import TimestampUnixGenerator
from .uuid import UUIDGenerator
from .weighted import WeightedGenerator

#: Canonical built-in generator classes. Used as the allowlist for
#: ``ton._registry.default_registry`` so in-process test fixtures or
#: third-party subclasses (which still appear in
#: ``Generator.__subclasses__()``) do not leak into the default registry
#: (TODO ARCH-005).
BUILTIN_GENERATOR_CLASSES: tuple[type[Generator], ...] = (
    BooleanGenerator,
    BytesGenerator,
    CharGenerator,
    DateGenerator,
    DecimalGenerator,
    EmailGenerator,
    IPv4Generator,
    IPv6Generator,
    IntegerGenerator,
    LMHashGenerator,
    MACGenerator,
    NameGenerator,
    PhoneGenerator,
    RegexGenerator,
    SequenceGenerator,
    StringGenerator,
    TextGenerator,
    TimestampUnixGenerator,
    UUIDGenerator,
    WeightedGenerator,
)

__all__ = [
    "BUILTIN_GENERATOR_CLASSES",
    "BooleanGenerator",
    "BytesGenerator",
    "CharGenerator",
    "DateGenerator",
    "DecimalGenerator",
    "EmailGenerator",
    "Generator",
    "IPv4Generator",
    "IPv6Generator",
    "IntegerGenerator",
    "LMHashGenerator",
    "MACGenerator",
    "NameGenerator",
    "PairedGenerator",
    "PhoneGenerator",
    "RegexGenerator",
    "SequenceGenerator",
    "StringGenerator",
    "TextGenerator",
    "TimestampUnixGenerator",
    "UUIDGenerator",
    "WeightedGenerator",
]
