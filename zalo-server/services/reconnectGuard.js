// Mỗi lần reconnect có một "generation" riêng. Login SDK không hỗ trợ abort,
// nên một lần đã timeout vẫn có thể hoàn tất muộn. Guard này ngăn lần cũ ghi
// đè account, cookie hoặc listener của lần thử mới hơn.
export function beginReconnectAttempt(states, ownId, state) {
  state.generation = (state.generation || 0) + 1;
  const generation = state.generation;
  return () => states.get(ownId) === state && state.generation === generation;
}

export function invalidateReconnectAttempt(state) {
  state.generation = (state.generation || 0) + 1;
}
