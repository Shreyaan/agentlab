const DEFAULT_FIXTURE_PORT = 8900;
const DEFAULT_SERVE_PORT = 8800;
const DEFAULT_IMAGE = "agentlab:latest";

/** Value of `--name value` or `--name=value` in argv; undefined when absent. */
function flagValue(argv, name) {
  const i = argv.indexOf(name);
  if (i !== -1) return argv[i + 1] ?? "";
  return argv.find((arg) => arg.startsWith(`${name}=`))?.slice(name.length + 1);
}

function parsePort(value, label) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`invalid ${label} "${value}" (expected 1-65535)`);
  }
  return port;
}

/** Pass a host env var through by name so its value never appears in argv; otherwise set a default. */
function envFlag(env, name, fallback) {
  return env[name] !== undefined ? ["-e", name] : ["-e", `${name}=${fallback}`];
}

/**
 * Build the `docker` argv that runs the agentlab image against the current directory.
 * Pure: all process state is passed in.
 */
export function buildDockerArgs({ argv, cwd, env, uid, gid, isTTY }) {
  const fixturePort = parsePort(
    flagValue(argv, "--fixture-port") ?? (env.AGENTLAB_FIXTURE_PORT || DEFAULT_FIXTURE_PORT),
    "--fixture-port",
  );
  const args = ["run", "--rm", "-i"];
  if (isTTY) args.push("-t");
  args.push("-v", `${cwd}:/work`, "-w", "/work", "--add-host", "host.docker.internal:host-gateway");
  if (typeof uid === "number" && typeof gid === "number") args.push("-u", `${uid}:${gid}`);

  const publish = [fixturePort];
  if (argv[0] === "serve") {
    const servePort = parsePort(flagValue(argv, "--port") ?? DEFAULT_SERVE_PORT, "--port");
    if (servePort !== fixturePort) publish.push(servePort);
  }
  // Unauthenticated services: publish on host loopback only, unless the user explicitly opts in to wider exposure.
  const publishHost = env.AGENTLAB_PUBLISH_HOST || "127.0.0.1";
  for (const port of publish) args.push("-p", `${publishHost}:${port}:${port}`);

  args.push(...envFlag(env, "AGENTLAB_FIXTURE_BIND", "0.0.0.0"));
  args.push(...envFlag(env, "AGENTLAB_FIXTURE_URL", `http://127.0.0.1:${fixturePort}/`));
  if (env.OPENROUTER_API_KEY) args.push("-e", "OPENROUTER_API_KEY");
  if (env.AGENTLAB_DATABASE_URL) args.push("-e", "AGENTLAB_DATABASE_URL");

  const userArgs = [...argv];
  // Servers inside the container must listen on all interfaces to be reachable through the published port.
  if ((argv[0] === "serve" || argv[0] === "fixture") && flagValue(argv, "--bind") === undefined) {
    userArgs.push("--bind", "0.0.0.0");
  }
  args.push(env.AGENTLAB_IMAGE || DEFAULT_IMAGE, ...userArgs);
  return args;
}

/**
 * Environment for the `docker` process itself. Values passed by name (`-e NAME`) are read from here, so secrets
 * never appear in argv. A database on the host's loopback is unreachable from the container, so it is rewritten
 * to host.docker.internal.
 */
export function buildDockerEnv(env) {
  const url = env.AGENTLAB_DATABASE_URL;
  if (!url) return env;
  return { ...env, AGENTLAB_DATABASE_URL: url.replace(/@(localhost|127\.0\.0\.1|\[::1\])([:/])/, "@host.docker.internal$2") };
}
