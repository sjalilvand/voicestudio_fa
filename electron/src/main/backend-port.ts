import { createServer } from 'node:net';

/** Check bind permissions without leaving a listener behind. */
function probePort(port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      const address = server.address();
      server.close((error) => {
        if (error) reject(error);
        else if (address && typeof address !== 'string') resolve(address.port);
        else reject(new Error('Backend port probe did not bind'));
      });
    });
  });
}

/** Reserved Windows ports can deny bind even though no process is listening.
 * Preserve ordinary port-conflict/attachment handling; only bypass denied ports.
 * This is a preflight, not a reservation: uvicorn still handles bind-time races.
 */
export async function availableBackendPort(preferred: number): Promise<number> {
  try {
    await probePort(preferred);
    return preferred;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === 'EADDRINUSE') return preferred;
    if (code !== 'EACCES') throw error;
    return probePort(0);
  }
}
