export function createConnectionLimit(maximum, activeCount) {
  let reserved = 0;
  const hasRoom = () => activeCount() + reserved < maximum;
  return {
    tryReserve() {
      if (!hasRoom()) return false;
      reserved += 1;
      return true;
    },
    confirm() {
      reserved = Math.max(0, reserved - 1);
    },
    release() {
      reserved = Math.max(0, reserved - 1);
    },
    pending() {
      return reserved;
    },
  };
}
