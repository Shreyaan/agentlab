import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDockerArgs, buildDockerEnv } from "../src/docker-args.mjs";

const base = { cwd: "/repo", env: {}, uid: undefined, gid: undefined, isTTY: false };
const run = (argv, overrides = {}) => buildDockerArgs({ ...base, argv, ...overrides });
/** True when `seq` appears as a contiguous run in args. */
const contains = (args, ...seq) => args.some((_, i) => seq.every((value, j) => args[i + j] === value));

test("test command mounts cwd, publishes fixture port, and forwards argv to the image", () => {
  const args = run(["test", "scenarios", "--candidate", "ts-fixed"]);
  assert.deepEqual(args.slice(0, 3), ["run", "--rm", "-i"]);
  assert.ok(contains(args, "-v", "/repo:/work"));
  assert.ok(contains(args, "-w", "/work"));
  assert.ok(contains(args, "--add-host", "host.docker.internal:host-gateway"));
  assert.ok(contains(args, "-p", "127.0.0.1:8900:8900"));
  assert.ok(!args.includes("-t"));
  assert.ok(!args.includes("-u"));
  assert.ok(contains(args, "-e", "AGENTLAB_FIXTURE_BIND=0.0.0.0"));
  assert.ok(contains(args, "-e", "AGENTLAB_FIXTURE_URL=http://127.0.0.1:8900/"));
  assert.deepEqual(args.slice(args.indexOf("agentlab:latest")), ["agentlab:latest", "test", "scenarios", "--candidate", "ts-fixed"]);
});

test("custom --fixture-port is published and used in the default fixture URL", () => {
  for (const argv of [["test", "s", "--fixture-port", "8901"], ["test", "s", "--fixture-port=8901"]]) {
    const args = run(argv);
    assert.ok(contains(args, "-p", "127.0.0.1:8901:8901"));
    assert.ok(!args.includes("127.0.0.1:8900:8900"));
    assert.ok(contains(args, "-e", "AGENTLAB_FIXTURE_URL=http://127.0.0.1:8901/"));
  }
});

test("AGENTLAB_FIXTURE_PORT env sets the fixture port when no flag is given", () => {
  const args = run(["test", "s"], { env: { AGENTLAB_FIXTURE_PORT: "8903" } });
  assert.ok(contains(args, "-p", "127.0.0.1:8903:8903"));
});

test("serve also publishes 8800, or its --port value", () => {
  assert.ok(contains(run(["serve"]), "-p", "127.0.0.1:8800:8800"));
  const args = run(["serve", "--port", "8810"]);
  assert.ok(contains(args, "-p", "127.0.0.1:8810:8810"));
  assert.ok(!args.includes("127.0.0.1:8800:8800"));
});

test("serve does not double-publish when its port equals the fixture port", () => {
  const args = run(["serve", "--port", "8900"]);
  assert.equal(args.filter((a) => a === "127.0.0.1:8900:8900").length, 1);
});

test("env-set fixture URL is passed by name, so its value never reaches argv", () => {
  const args = run(["test", "s"], { env: { AGENTLAB_FIXTURE_URL: "http://gw.example:9/" } });
  assert.ok(contains(args, "-e", "AGENTLAB_FIXTURE_URL"));
  assert.ok(!args.some((a) => a.includes("gw.example")));
  assert.ok(!args.some((a) => a.includes("http://127.0.0.1:8900")));
});

test("uid/gid map to -u only when both are numbers", () => {
  assert.ok(contains(run(["test", "s"], { uid: 1000, gid: 1000 }), "-u", "1000:1000"));
  assert.ok(!run(["test", "s"], { uid: 1000 }).includes("-u"));
});

test("TTY flag adds -t only when attached to a terminal", () => {
  assert.ok(run(["test", "s"], { isTTY: true }).includes("-t"));
  assert.ok(!run(["test", "s"], { isTTY: false }).includes("-t"));
});

test("OPENROUTER_API_KEY is passed by name and its value never appears in argv", () => {
  const args = run(["test", "s"], { env: { OPENROUTER_API_KEY: "sk-secret-123" } });
  assert.ok(contains(args, "-e", "OPENROUTER_API_KEY"));
  assert.ok(!args.some((a) => a.includes("sk-secret-123")));
  assert.ok(!run(["test", "s"]).includes("OPENROUTER_API_KEY"));
});

test("AGENTLAB_IMAGE overrides the default image", () => {
  const args = run(["test", "s"], { env: { AGENTLAB_IMAGE: "ghcr.io/acme/agentlab:0.3.0" } });
  assert.ok(args.includes("ghcr.io/acme/agentlab:0.3.0"));
});

test("invalid port values are rejected", () => {
  assert.throws(() => run(["test", "s", "--fixture-port", "abc"]), /--fixture-port/);
  assert.throws(() => run(["test", "s", "--fixture-port"]), /--fixture-port/);
  assert.throws(() => run(["serve", "--port", "70000"]), /--port/);
});

test("database URL is passed by name and loopback is rewritten for the container", () => {
  const env = { AGENTLAB_DATABASE_URL: "postgresql://u:secret@127.0.0.1:55432/agentlab" };
  const args = buildDockerArgs({ argv: ["test", "scenarios"], cwd: "/w", env, isTTY: false });
  assert.ok(args.includes("AGENTLAB_DATABASE_URL"));
  assert.ok(!args.some((a) => a.includes("secret")));
  assert.equal(buildDockerEnv(env).AGENTLAB_DATABASE_URL, "postgresql://u:secret@host.docker.internal:55432/agentlab");
  assert.equal(buildDockerEnv({ AGENTLAB_DATABASE_URL: "postgresql://u:p@db.internal:5432/x" }).AGENTLAB_DATABASE_URL,
    "postgresql://u:p@db.internal:5432/x");
});

test("serve binds all interfaces inside the container unless --bind is given", () => {
  const base = { cwd: "/w", env: {}, isTTY: false };
  assert.deepEqual(buildDockerArgs({ ...base, argv: ["serve"] }).slice(-3), ["serve", "--bind", "0.0.0.0"]);
  assert.deepEqual(buildDockerArgs({ ...base, argv: ["serve", "--bind", "1.2.3.4"] }).slice(-3), ["serve", "--bind", "1.2.3.4"]);
});

test("ports publish on host loopback unless AGENTLAB_PUBLISH_HOST opts in", () => {
  const args = buildDockerArgs({ argv: ["serve"], cwd: "/w", env: {}, isTTY: false });
  assert.ok(args.every((a) => !/^\d+:\d+$/.test(a)), "no all-interface publish");
  const wide = buildDockerArgs({ argv: ["serve"], cwd: "/w", env: { AGENTLAB_PUBLISH_HOST: "0.0.0.0" }, isTTY: false });
  assert.ok(wide.includes("0.0.0.0:8800:8800"));
});

test("serve allows no token only on a loopback publish; a token is passed by name", () => {
  const base = { argv: ["serve"], cwd: "/w", isTTY: false };
  assert.ok(buildDockerArgs({ ...base, env: {} }).includes("AGENTLAB_ALLOW_NO_TOKEN=1"));
  assert.ok(!buildDockerArgs({ ...base, env: { AGENTLAB_PUBLISH_HOST: "0.0.0.0" } }).includes("AGENTLAB_ALLOW_NO_TOKEN=1"));
  const withToken = buildDockerArgs({ ...base, env: { AGENTLAB_CONSOLE_TOKEN: "s3cret" } });
  assert.ok(withToken.includes("AGENTLAB_CONSOLE_TOKEN"));
  assert.ok(!withToken.some((a) => a.includes("s3cret")));
});
