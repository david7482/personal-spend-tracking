from spend_tracking.interfaces.email_parser import EmailParser
from spend_tracking.lambdas.services.parsers.cathay import CathayParser

_PARSERS: list[EmailParser] = [
    CathayParser(),
]


def find_parser(to_address: str, subject: str) -> EmailParser | None:
    for parser in _PARSERS:
        if parser.can_parse(to_address, subject):
            return parser
    return None
