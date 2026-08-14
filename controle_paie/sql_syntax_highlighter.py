from __future__ import annotations

import re


class SqlSyntaxHighlighter:
    """Coloration syntaxique légère pour le widget Tk Text de la console SQL."""

    KEYWORDS = {
        "SELECT", "FROM", "WHERE", "AS", "DISTINCT", "ALL", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER",
        "CROSS", "ON", "USING", "AND", "OR", "NOT", "IN", "BETWEEN", "LIKE", "ILIKE", "IS", "NULL", "TRUE",
        "FALSE", "ORDER", "BY", "ASC", "DESC", "GROUP", "HAVING", "LIMIT", "OFFSET", "WITH", "RECURSIVE", "UNION",
        "INTERSECT", "EXCEPT", "CASE", "WHEN", "THEN", "ELSE", "END", "OVER", "PARTITION", "ROWS", "RANGE",
        "UNBOUNDED", "PRECEDING", "FOLLOWING", "CURRENT", "ROW", "EXISTS", "QUALIFY", "WINDOW", "FILTER", "NULLS",
        "FIRST", "LAST", "EXPLAIN", "DESCRIBE"
    }
    FUNCTIONS = {
        "COUNT", "SUM", "AVG", "MIN", "MAX", "COALESCE", "NULLIF", "CAST", "TRY_CAST", "TRIM", "LTRIM", "RTRIM",
        "UPPER", "LOWER", "CONCAT", "ROUND", "ABS", "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE",
        "LAST_VALUE", "LENGTH", "REPLACE", "REGEXP_REPLACE", "SUBSTRING", "DATE_TRUNC", "STRFTIME"
    }
    TOKEN_RE = re.compile(
        r"(?P<comment>--[^\n]*|/\*.*?\*/)|(?P<string>'(?:''|[^'])*')|(?P<quoted>\"(?:\"\"|[^\"])*\")|"
        r"(?P<number>\b\d+(?:\.\d+)?\b)|(?P<word>\b[A-Za-z_][A-Za-z0-9_]*\b)",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def configure(cls, text):
        text.tag_configure("sql_keyword", foreground="#005CC5", font=("DejaVu Sans Mono", 10, "bold"))
        text.tag_configure("sql_function", foreground="#6F42C1")
        text.tag_configure("sql_string", foreground="#A31515")
        text.tag_configure("sql_comment", foreground="#22863A")
        text.tag_configure("sql_number", foreground="#B31D28")
        text.tag_configure("sql_identifier", foreground="#795E26")

    @classmethod
    def highlight(cls, text):
        content = text.get("1.0", "end-1c")
        for tag in ("sql_keyword", "sql_function", "sql_string", "sql_comment", "sql_number", "sql_identifier"):
            text.tag_remove(tag, "1.0", "end")
        for match in cls.TOKEN_RE.finditer(content):
            kind = match.lastgroup
            token = match.group(0)
            tag = None
            if kind == "comment": tag = "sql_comment"
            elif kind == "string": tag = "sql_string"
            elif kind == "quoted": tag = "sql_identifier"
            elif kind == "number": tag = "sql_number"
            elif kind == "word":
                upper = token.upper()
                if upper in cls.KEYWORDS: tag = "sql_keyword"
                elif upper in cls.FUNCTIONS: tag = "sql_function"
            if tag:
                start = f"1.0+{match.start()}c"
                end = f"1.0+{match.end()}c"
                text.tag_add(tag, start, end)
