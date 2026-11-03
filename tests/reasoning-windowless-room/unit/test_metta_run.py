#!/usr/bin/env python3
"""Unit tests for the upstream-pinned MeTTa runtime wrapper
(skills-sut/metta/metta_run.py — spec addendum items 2 and 6).

Fixtures are byte-accurate excerpts of the VERIFIED live output of the
pinned runtime (swipl:10.0.2 + PeTTa v1.0.4 @7037f4c2, captured running
the NAL probe on 2026-11-03 — including the ANSI color codes the
interpreter emits on stdout), so the trace-noise filtering is pinned
against the real shapes:

    --> ... -->        trace headers (metta function / prolog clause /
                       metta sexpr / metta runnable / prolog goal)
    ^^^^               block separators
    :- findall(...)    goal echoes inside the prolog-goal block
    true               the RESULTS of the two !(import! ...) forms
    <result line>      the evaluation's own result (last printed line)

The swipl subprocess is mocked; the invocation shape (binary, flags,
cwd, timeout), the temp program file (workspace-local .metta-tmp/, two
absolute-path import! lines + !expr, removed afterwards), the status
mapping (nonzero exit / timeout / missing runtime / missing lib ->
metta_error; input-shape errors -> syntax_error), the (metta "...")
unwrap, the !-prefix handling and the empty-result `()` contract are all
asserted.
"""

import os
import subprocess
import sys
import tempfile
import types
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO_ROOT, "skills-sut", "metta"))

import metta_run  # noqa: E402

ESCAPE = "\x1b["

# --- byte-accurate fixture: head of the verified NAL-probe run ------------
# (import! runnable + goal echo + a function/clause block, ANSI-colored)
REAL_TRACE_HEAD = (
    ESCAPE
    + "33m--> metta runnable  -->\n"
    + ESCAPE
    + '36m!(import! &self "/opt/sut-metta/lib_nal.metta")\n'
    + ESCAPE
    + "33m-->  prolog goal  -->"
    + ESCAPE
    + "35m \n"
    + ":- findall(A,\n"
    + "           'import!'('&self',\n"
    + '                     "/opt/sut-metta/lib_nal.metta",\n'
    + "                     A),\n"
    + "           _).\n"
    + ESCAPE
    + "33m^^^^^^^^^^^^^^^^^^^^^^^\n"
    + ESCAPE
    + "0m"
    + ESCAPE
    + "33m--> metta function -->\n"
    + ESCAPE
    + "36m(= (Truth_c2w $c)\n"
    + "   (/ $c (- 1 $c)))\n"
    + ESCAPE
    + "33m--> prolog clause -->\n"
    + ESCAPE
    + "32m'Truth_c2w'(A, B) :-\n"
    + "    -(1, A, C),\n"
    + "    '/safe'(A, C, B).\n"
    + ESCAPE
    + "33m^^^^^^^^^^^^^^^^^^^^^^\n"
    + ESCAPE
    + "0m"
)

# --- byte-accurate fixture: tail of the verified NAL-probe run ------------
# (the eval's runnable + goal echo + the two import `true` results + the
# derived-atom result — exactly as the pinned runtime prints them)
REAL_TRACE_TAIL = (
    ESCAPE
    + "33m--> metta runnable  -->\n"
    + ESCAPE
    + "36m!(|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9)))\n"
    + ESCAPE
    + "33m-->  prolog goal  -->"
    + ESCAPE
    + "35m \n"
    + ":- findall(A,\n"
    + "           '|-'([[-->, garfield, animal], [stv, 1.0, 0.9]],\n"
    + "                [[-->, garfield, mammal], [stv, 1.0, 0.9]],\n"
    + "                A),\n"
    + "           _).\n"
    + ESCAPE
    + "33m^^^^^^^^^^^^^^^^^^^^^^^\n"
    + ESCAPE
    + "0mtrue\n"
    + "true\n"
    + "(((--> mammal animal) (stv 1.0 0.44751381215469616)) ((<-> mammal animal)"
    + " (stv 1.0 0.44751381215469616)) ((--> animal mammal)"
    + " (stv 1.0 0.44751381215469616)) ((<-> animal mammal)"
    + " (stv 1.0 0.44751381215469616)))\n"
)

REAL_RESULT_LINE = (
    "(((--> mammal animal) (stv 1.0 0.44751381215469616)) ((<-> mammal animal)"
    + " (stv 1.0 0.44751381215469616)) ((--> animal mammal)"
    + " (stv 1.0 0.44751381215469616)) ((<-> animal mammal)"
    + " (stv 1.0 0.44751381215469616)))"
)

# byte-accurate stderr of the pinned runtime on an unbalanced-paren input
REAL_SYNTAX_STDERR = (
    "ERROR: [Thread main] /opt/petta/src/main.pl:23: user:main "
    "Syntax error: missing ')', starting at line 3:\n"
    "|- ((--> a b) (stv 1.0 0.9)) ((--> a c) (stv 1.0 0.9))\n"
)


# --- test scaffolding ------------------------------------------------------


class _FakeSwipl:
    """subprocess.run replacement capturing the invocation."""

    def __init__(self, stdout="", stderr="", returncode=0, exc=None):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.exc = exc
        self.calls = []
        self.programs = []  # program file contents, snapshotted at call time

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        try:
            with open(cmd[-1]) as f:
                self.programs.append(f.read())
        except OSError:
            self.programs.append(None)
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(returncode=self.returncode,
                               stdout=self.stdout, stderr=self.stderr)


class _Env:
    """Scoped env + fake-vendored-libs sandbox."""

    def __init__(self):
        self._old_environ = os.environ.copy()
        self._old_run = metta_run.subprocess.run
        self.tmp = tempfile.mkdtemp(prefix="metta-run-test-")
        self.lib_dir = os.path.join(self.tmp, "libs")
        os.makedirs(self.lib_dir)
        for lib in (metta_run.LIB_NAL, metta_run.LIB_PLN):
            with open(os.path.join(self.lib_dir, lib), "w") as f:
                f.write(f"; fake {lib}\n")
        os.environ["OPENCLAW_SUT_WORKSPACE"] = os.path.join(self.tmp, "ws")
        os.makedirs(os.environ["OPENCLAW_SUT_WORKSPACE"])
        os.environ["OPENCLAW_SUT_METTA_LIB_DIR"] = self.lib_dir

    def install_fake(self, **kw):
        fake = _FakeSwipl(**kw)
        metta_run.subprocess.run = fake
        return fake

    def close(self):
        metta_run.subprocess.run = self._old_run
        os.environ.clear()
        os.environ.update(self._old_environ)
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


# --- trace filtering (spec addendum: noise vs result lines) ---------------


def test_filter_real_probe_output_keeps_only_result():
    text = REAL_TRACE_HEAD + REAL_TRACE_TAIL
    assert metta_run._filter_output(text) == [REAL_RESULT_LINE]


def test_filter_drops_goal_echo_trues_and_carets():
    kept = metta_run._filter_output(REAL_TRACE_TAIL)
    assert kept == [REAL_RESULT_LINE]
    assert all(l != "true" for l in kept)
    assert all("findall" not in l for l in kept)
    assert all("^^" not in l for l in kept)


def test_filter_keeps_native_empty_paren_result():
    # a no-derivation eval prints () natively (verified live): the filter
    # must keep it while dropping the two import `true` lines
    text = REAL_TRACE_HEAD + ESCAPE + "0mtrue\ntrue\n()\n"
    assert metta_run._filter_output(text) == ["()"]


def test_filter_multiple_result_lines_kept():
    text = REAL_TRACE_HEAD + ESCAPE + "0mtrue\ntrue\n(atom-a)\n(atom-b)\n"
    assert metta_run._filter_output(text) == ["(atom-a)", "(atom-b)"]


def test_filter_strips_ansi_from_result_lines():
    text = ESCAPE + "36m((--> a b) (stv 1.0 0.9))\n" + ESCAPE + "0m\n"
    assert metta_run._filter_output(text) == ["((--> a b) (stv 1.0 0.9))"]


def test_filter_stray_caret_and_goal_lines_outside_blocks_dropped():
    text = "^^^^^^^^^^^^^^^^^^^^^^\n:- findall(A, X, _).\n(some result)\n"
    assert metta_run._filter_output(text) == ["(some result)"]


def test_filter_empty_text_is_empty():
    assert metta_run._filter_output("") == []


# --- status mapping -------------------------------------------------------


def test_nonzero_exit_maps_to_metta_error():
    env = _Env()
    try:
        fake = env.install_fake(stdout="", stderr=REAL_SYNTAX_STDERR, returncode=2)
        out, ok = metta_run.run_expression(
            "(|- ((--> a b) (stv 1.0 0.9)) ((--> a c) (stv 1.0 0.9))")
        assert not ok
        assert out.startswith("metta_error: swipl exited 2:")
        assert "Syntax error: missing ')'" in out
        assert len(fake.calls) == 1
    finally:
        env.close()


def test_timeout_maps_to_metta_error():
    env = _Env()
    try:
        env.install_fake(exc=subprocess.TimeoutExpired(cmd="swipl", timeout=120))
        out, ok = metta_run.run_expression("(|- ((--> a b) (stv 1.0 0.9)))")
        assert not ok
        assert out == f"metta_error: swipl timeout after 120s"
    finally:
        env.close()


def test_swipl_missing_maps_to_metta_error():
    env = _Env()
    try:
        env.install_fake(exc=FileNotFoundError("/usr/bin/swipl"))
        out, ok = metta_run.run_expression("(|- ((--> a b) (stv 1.0 0.9)))")
        assert not ok
        assert out.startswith("metta_error: swipl runtime unavailable:")
    finally:
        env.close()


def test_missing_lib_maps_to_metta_error_without_running_swipl():
    env = _Env()
    try:
        os.remove(os.path.join(env.lib_dir, metta_run.LIB_PLN))
        fake = env.install_fake(stdout="unused")
        out, ok = metta_run.run_expression("(|- ((--> a b) (stv 1.0 0.9)))")
        assert not ok
        assert out.startswith("metta_error: vendored metta lib missing:")
        assert metta_run.LIB_PLN in out
        assert fake.calls == []  # the runtime never runs with a missing lib
    finally:
        env.close()


def test_empty_expression_is_syntax_error():
    out, ok = metta_run.run_expression("   ")
    assert not ok
    assert out == "syntax_error: empty expression"


def test_oversized_expression_is_syntax_error():
    out, ok = metta_run.run_expression("(foo " + "a" * 5000 + ")")
    assert not ok
    assert out == f"syntax_error: expression exceeds {metta_run.MAX_EXPR_CHARS} characters"


# --- success path: invocation shape, program file, unwrap, results --------


def test_swipl_invocation_shape_and_result():
    env = _Env()
    try:
        fake = env.install_fake(stdout=REAL_TRACE_HEAD + REAL_TRACE_TAIL)
        out, ok = metta_run.run_expression(
            "(|- ((--> garfield animal) (stv 1.0 0.9))"
            " ((--> garfield mammal) (stv 1.0 0.9)))")
        assert ok
        assert out == REAL_RESULT_LINE
        cmd, kw = fake.calls[0]
        assert cmd[0] == "/usr/bin/swipl"
        assert cmd[1:4] == ["--stack_limit=8g", "-q", "-s"]
        assert cmd[4] == "src/main.pl"  # relative — cwd must be the PeTTa dir
        assert cmd[5] == "--"
        assert cmd[6].endswith(".metta")
        assert kw["cwd"] == "/opt/petta"
        assert kw["timeout"] == 120
    finally:
        env.close()


def test_program_file_contents_and_cleanup():
    env = _Env()
    try:
        fake = env.install_fake(stdout="()\n")
        expr = "(|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9)))"
        metta_run.run_expression(expr)
        program_file = fake.calls[0][0][6]
        assert program_file.startswith(
            os.path.join(os.environ["OPENCLAW_SUT_WORKSPACE"], ".metta-tmp"))
        # the temp file is removed after the run
        assert not os.path.exists(program_file)
    finally:
        env.close()


def test_wrapped_metta_call_is_unwrapped_into_program():
    env = _Env()
    try:
        fake = env.install_fake(stdout="()\n")
        wrapped = ('(metta "(|- ((--> garfield animal) (stv 1.0 0.9))'
                   ' ((--> garfield mammal) (stv 1.0 0.9)))")')
        metta_run.run_expression(wrapped)
        program = fake.programs[0]
        assert program.startswith(
            f'!(import! &self "{os.path.join(env.lib_dir, "lib_nal.metta")}")\n')
        assert f'!(import! &self "{os.path.join(env.lib_dir, "lib_pln.metta")}")\n' in program
        assert program.endswith(
            "!(|- ((--> garfield animal) (stv 1.0 0.9))"
            " ((--> garfield mammal) (stv 1.0 0.9)))\n")
        # the (metta ...) wrapper itself never reaches the interpreter
        assert "(metta " not in program
    finally:
        env.close()


def test_bang_prefix_tolerated_not_duplicated():
    env = _Env()
    try:
        fake = env.install_fake(stdout="()\n")
        metta_run.run_expression("!(foo bar)")
        program = fake.programs[0]
        lines = program.splitlines()
        assert len(lines) == 3  # two import! lines + one eval line
        assert lines[-1] == "!(foo bar)"  # exactly one eval prefix, not "!!"
    finally:
        env.close()


def test_empty_filtered_result_prints_empty_parens():
    env = _Env()
    try:
        # stdout with ONLY trace noise (no result lines printed)
        env.install_fake(stdout=REAL_TRACE_HEAD)
        out, ok = metta_run.run_expression("(unknown-op a b)")
        assert ok
        assert out == "()"
    finally:
        env.close()


def test_unwrap_quoted_payload_escapes():
    unwrapped = metta_run._unwrap_metta_call('(metta "(say \\"hi\\")")')
    assert unwrapped == '(say "hi")'


# --- R-S8: best-effort history episode -------------------------------------


def test_main_appends_history_episode():
    env = _Env()
    try:
        import io
        import contextlib
        env.install_fake(stdout=REAL_TRACE_HEAD + REAL_TRACE_TAIL)
        expr = "(|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9)))"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = metta_run.main([expr])
        assert rc == 0
        assert buf.getvalue() == REAL_RESULT_LINE + "\n"
        history = open(os.path.join(
            os.environ["OPENCLAW_SUT_WORKSPACE"], "history.metta")).read()
        assert "; " in history and " metta eval\n" in history
        assert expr in history and REAL_RESULT_LINE in history
    finally:
        env.close()


def test_main_usage_error_exits_two():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rc = metta_run.main([])
    assert rc == 2


# --- helpers ---------------------------------------------------------------