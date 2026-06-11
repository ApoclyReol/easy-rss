from __future__ import annotations

import re
from dataclasses import dataclass

SEARCHABLE_FIELDS = ("title", "authors", "journal", "summary", "doi")
VALID_FIELDS = frozenset(SEARCHABLE_FIELDS)

TOKEN_RE = re.compile(
    r"""
    (?P<SPACE>\s+)
    |(?P<LPAREN>\()
    |(?P<RPAREN>\))
    |(?P<COLON>:)
    |(?P<QUOTED>"(?:[^"\\]|\\.)*")
    |(?P<WORD>[^\s():"]+)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class TermNode:
    text: str
    field: str | None = None


@dataclass(frozen=True)
class NotNode:
    child: object


@dataclass(frozen=True)
class AndNode:
    left: object
    right: object


@dataclass(frozen=True)
class OrNode:
    left: object
    right: object


@dataclass(frozen=True)
class FieldNode:
    field: str
    child: object


class BooleanExpressionError(ValueError):
    pass


def _unquote(token: str) -> str:
    if token.startswith('"') and token.endswith('"'):
        inner = token[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return token


def tokenize(expression: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(expression):
        match = TOKEN_RE.match(expression, index)
        if not match:
            snippet = expression[index : index + 20]
            raise BooleanExpressionError(f"无法解析的表达式片段：{snippet}")
        kind = match.lastgroup
        value = match.group(0)
        index = match.end()
        if kind == "SPACE":
            continue
        tokens.append((kind, value))
    return tokens


class Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> object:
        if not self.tokens:
            raise BooleanExpressionError("表达式不能为空")
        node = self.parse_or()
        if self.pos != len(self.tokens):
            raise BooleanExpressionError("表达式末尾有未识别内容")
        return node

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def pop(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise BooleanExpressionError("表达式意外结束")
        self.pos += 1
        return token

    def match_word(self, word: str) -> bool:
        token = self.peek()
        return bool(token and token[0] == "WORD" and token[1].upper() == word)

    def parse_or(self) -> object:
        node = self.parse_and()
        while self.match_word("OR"):
            self.pop()
            node = OrNode(node, self.parse_and())
        return node

    def parse_and(self) -> object:
        node = self.parse_not()
        while self.match_word("AND"):
            self.pop()
            node = AndNode(node, self.parse_not())
        return node

    def parse_not(self) -> object:
        if self.match_word("NOT"):
            self.pop()
            return NotNode(self.parse_not())
        return self.parse_primary()

    def parse_primary(self) -> object:
        token = self.peek()
        if token is None:
            raise BooleanExpressionError("表达式意外结束")

        if token[0] == "WORD":
            if token[1].upper() in {"AND", "OR"}:
                raise BooleanExpressionError(f"运算符 {token[1]} 前缺少查询项")
            if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1][0] == "COLON":
                field = token[1].lower()
                if field not in VALID_FIELDS:
                    raise BooleanExpressionError(f"不支持的字段限定：{field}")
                self.pop()
                self.pop()
                return FieldNode(field, self.parse_primary())
            self.pop()
            return TermNode(_unquote(token[1]))

        if token[0] == "QUOTED":
            self.pop()
            return TermNode(_unquote(token[1]))

        if token[0] == "LPAREN":
            self.pop()
            node = self.parse_or()
            closing = self.pop()
            if closing[0] != "RPAREN":
                raise BooleanExpressionError("缺少右括号 )")
            return node

        raise BooleanExpressionError(f"无法识别的查询项：{token[1]}")


def parse_boolean_expression(expression: str) -> object:
    return Parser(tokenize(expression)).parse()


def _matches_term(item: dict, text: str, field: str | None) -> bool:
    needle = text.casefold().strip()
    if not needle:
        return False
    haystacks = [field] if field else SEARCHABLE_FIELDS
    for key in haystacks:
        value = str(item.get(key) or "")
        if needle in value.casefold():
            return True
    return False


def evaluate_expression(node: object, item: dict, inherited_field: str | None = None) -> bool:
    if isinstance(node, TermNode):
        return _matches_term(item, node.text, node.field or inherited_field)
    if isinstance(node, FieldNode):
        return evaluate_expression(node.child, item, inherited_field=node.field)
    if isinstance(node, NotNode):
        return not evaluate_expression(node.child, item, inherited_field=inherited_field)
    if isinstance(node, AndNode):
        return evaluate_expression(node.left, item, inherited_field=inherited_field) and evaluate_expression(
            node.right,
            item,
            inherited_field=inherited_field,
        )
    if isinstance(node, OrNode):
        return evaluate_expression(node.left, item, inherited_field=inherited_field) or evaluate_expression(
            node.right,
            item,
            inherited_field=inherited_field,
        )
    raise TypeError(f"Unsupported node type: {type(node)!r}")


def filter_items_by_expression(items: list[dict], expression: str) -> list[dict]:
    tree = parse_boolean_expression(expression)
    return [item for item in items if evaluate_expression(tree, item)]

