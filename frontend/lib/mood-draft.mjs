/** Serialize draft writes so older autosaves cannot overwrite newer composition snapshots.
 * @returns {(save: () => unknown | Promise<unknown>) => Promise<unknown>}
 */
export function createSerializedSaveQueue() {
  let previous = Promise.resolve();
  return (save) => {
    const current = previous.catch(() => undefined).then(save);
    previous = current.then(() => undefined, () => undefined);
    return current;
  };
}
