import unittest

from tpl import TemplateError, render


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Variables(unittest.TestCase):
    def test_lookup_dict_then_attribute_and_none(self):
        self.assertEqual(render("{{ a.b }}|{{ o.x.y }}|{{ n }}|{{ z.q }}", {"a": {"b": 1}, "o": Obj(x=Obj(y="Y")), "n": None}), "1|Y||")
        self.assertEqual(render("{{ d.items }}", {"d": {"items": "K"}}), "K")
        self.assertEqual(render("a {{x}} b {{  x  }}", {"x": 0}), "a 0 b 0")

    def test_text_untouched(self):
        self.assertEqual(render("<p>\n  & {not a tag} {% if t %}ok{% endif %}\n</p>", {"t": 1}), "<p>\n  & {not a tag} ok\n</p>")


class Filters(unittest.TestCase):
    def test_basic_filters(self):
        c = {"s": "hello world", "xs": [1, "b", None], "e": ""}
        self.assertEqual(render("{{ s|upper }} {{ s|title }} {{ s|upper|lower }}", c), "HELLO WORLD Hello World hello world")
        self.assertEqual(render("{{ s|length }} {{ xs|length }} {{ nope|length }}", c), "11 3 0")
        self.assertEqual(render("[{{ nope|upper }}] [{{ nope|title }}]", c), "[] []")
        self.assertEqual(render('{{ xs|join:", " }}', c), "1, b, ")
        self.assertEqual(render('[{{ nope|join:"-" }}]', c), "[]")

    def test_default_keeps_zero_and_false(self):
        c = {"zero": 0, "f": False, "e": "", "n": None, "v": "v"}
        self.assertEqual(render('{{ zero|default:"d" }}|{{ f|default:"d" }}|{{ e|default:"d" }}|{{ n|default:"d" }}|{{ m|default:"d" }}|{{ v|default:"d" }}', c), "0|False|d|d|d|v")

    def test_filter_args_and_pipes_in_strings(self):
        self.assertEqual(render('{{ xs|join:"|" }}', {"xs": ["a", "b"]}), "a|b")
        self.assertEqual(render('{{ xs | join:" - " | upper }}', {"xs": ["a", "b"]}), "A - B")

    def test_filter_errors(self):
        for tpl, msg in (("{{ x|nope }}", "unknown filter: nope"), ('{{ x|upper:"a" }}', "bad filter arguments: upper"),
                         ("{{ x|default }}", "bad filter arguments: default"), ("{{ x|join }}", "bad filter arguments: join"),
                         ('{{ x|safe:"a" }}', "bad filter arguments: safe"), ('{{ x|length:"a" }}', "bad filter arguments: length")):
            with self.assertRaises(TemplateError) as cm:
                render(tpl, {"x": "v"})
            self.assertEqual(str(cm.exception), msg)

    def test_error_before_any_output_and_in_dead_branch(self):
        with self.assertRaises(TemplateError):
            render("{% if a %}{{ x|nope }}{% endif %}", {})


class Escaping(unittest.TestCase):
    def test_escape_all_five(self):
        self.assertEqual(render("{{ x }}", {"x": "<a href=\"x\">&'</a>"}), "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;")

    def test_single_pass_no_double_escape(self):
        self.assertEqual(render("{{ x }}", {"x": "&amp;"}), "&amp;amp;")

    def test_safe_anywhere_in_chain(self):
        self.assertEqual(render("{{ x|safe|upper }} {{ x|upper|safe }} {{ x|upper }}", {"x": "<b>"}), "<B> <B> &lt;B&gt;")

    def test_join_output_escaped(self):
        self.assertEqual(render('{{ xs|join:"<br>" }}', {"xs": ["a", "b"]}), "a&lt;br&gt;b")
        self.assertEqual(render('{{ xs|join:"<br>"|safe }}', {"xs": ["a", "<b"]}), "a<br><b")

    def test_numbers_and_none(self):
        self.assertEqual(render("{{ n }}{{ z }}{{ t }}", {"n": 1.5, "z": None, "t": True}), "1.5True")


class Conditions(unittest.TestCase):
    def test_if_elif_else(self):
        t = "{% if a %}A{% elif b %}B{% elif not c %}C{% else %}D{% endif %}"
        self.assertEqual(render(t, {"a": 1}), "A")
        self.assertEqual(render(t, {"b": [0]}), "B")
        self.assertEqual(render(t, {"b": [], "c": 0}), "C")
        self.assertEqual(render(t, {"c": 1}), "D")
        self.assertEqual(render(t, {}), "C")

    def test_if_without_else_and_tight_spacing(self):
        self.assertEqual(render("[{%if a%}x{%endif%}]", {}), "[]")
        self.assertEqual(render("[{%  if  not  a  %}x{%  endif  %}]", {}), "[x]")

    def test_dotted_conditions(self):
        self.assertEqual(render("{% if u.admin %}root{% endif %}{% if not u.admin %}user{% endif %}", {"u": {"admin": False}}), "user")

    def test_first_true_branch_only(self):
        self.assertEqual(render("{% if a %}1{% elif a %}2{% endif %}", {"a": 1}), "1")


class Loops(unittest.TestCase):
    def test_loop_variables(self):
        t = "{% for x in xs %}{{ loop.index }}/{{ loop.index0 }}{% if loop.first %}F{% endif %}{% if loop.last %}L{% endif %}={{ x }};{% endfor %}"
        self.assertEqual(render(t, {"xs": "ab"}), "1/0F=a;2/1L=b;")
        self.assertEqual(render(t, {"xs": ["z"]}), "1/0FL=z;")

    def test_empty_and_missing(self):
        self.assertEqual(render("[{% for x in xs %}x{% endfor %}][{% for x in q %}x{% endfor %}][{% for x in n %}x{% endfor %}]", {"xs": [], "n": None}), "[][][]")

    def test_no_leak_and_caller_context_unchanged(self):
        ctx = {"xs": [1, 2], "x": "outer"}
        self.assertEqual(render("{% for x in xs %}{{ x }}{% endfor %}{{ x }}|{{ loop.index }}", ctx), "12outer|")
        self.assertEqual(ctx, {"xs": [1, 2], "x": "outer"})

    def test_nested_and_shadowing(self):
        t = "{% for r in rows %}{% for c in r %}{{ loop.index }}{% endfor %}{{ loop.index }},{% endfor %}"
        self.assertEqual(render(t, {"rows": [[1, 2, 3], [4]]}), "1231,12,")

    def test_if_inside_for_inside_if(self):
        t = "{% if xs %}{% for x in xs %}{% if x %}{{ x }}{% else %}-{% endif %}{% endfor %}{% else %}none{% endif %}"
        self.assertEqual(render(t, {"xs": [1, 0, 2]}), "1-2")
        self.assertEqual(render(t, {"xs": []}), "none")

    def test_filters_and_dotted_iterable(self):
        self.assertEqual(render("{% for t in post.tags %}{{ t|upper }} {% endfor %}", {"post": {"tags": ["a", "b"]}}), "A B ")


class Errors(unittest.TestCase):
    def check(self, tpl, msg):
        with self.assertRaises(TemplateError) as cm:
            render(tpl, {"a": 1, "xs": [1]})
        self.assertEqual(str(cm.exception), msg)

    def test_unclosed(self):
        self.check("{% if a %}x", "unclosed block: if")
        self.check("{% for x in xs %}x", "unclosed block: for")
        self.check("{% if a %}{% for x in xs %}x{% endfor %}", "unclosed block: if")
        self.check("{% for x in xs %}{% if a %}x{% endfor %}", "unexpected tag: endfor")
        self.check("{% for x in xs %}{% if a %}", "unclosed block: if")

    def test_unexpected(self):
        for name in ("elif a", "else", "endif", "endfor"):
            self.check("{% " + name + " %}", "unexpected tag: " + name.split()[0])
        self.check("{% if a %}x{% else %}y{% else %}z{% endif %}", "unexpected tag: else")
        self.check("{% if a %}x{% else %}y{% elif a %}z{% endif %}", "unexpected tag: elif")
        self.check("{% for x in xs %}{% else %}{% endfor %}", "unexpected tag: else")
        self.check("{% if a %}{% endfor %}{% endif %}", "unexpected tag: endfor")

    def test_unknown_and_bad(self):
        self.check("{% frobnicate a b %}", "unknown tag: frobnicate")
        self.check("{% for x xs %}{% endfor %}", "bad for tag: for x xs")
        self.check("{%  for x in  %}{% endfor %}", "bad for tag: for x in")
        self.check("{% for x in a b %}{% endfor %}", "bad for tag: for x in a b")
        self.check("{% if %}x{% endif %}", "bad if tag: if")
        self.check("{% if a b %}x{% endif %}", "bad if tag: if a b")
        self.check("{% if a %}x{% elif %}y{% endif %}", "bad if tag: elif")
        self.check("{% if not %}x{% endif %}", "bad if tag: if not")
        self.check("{% if not a b %}x{% endif %}", "bad if tag: if not a b")

    def test_error_is_raised_before_output(self):
        with self.assertRaises(TemplateError):
            render("{{ a }}{% if a %}", {"a": 1})

    def test_templateerror_is_valueerror_and_exported(self):
        self.assertTrue(issubclass(TemplateError, ValueError))


if __name__ == "__main__":
    unittest.main()
