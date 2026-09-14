import threading


class Subject:
    def __init__(self):
        self.observers = []  # a list of observers
        self.state = None
        # Re-entrant so observers may inspect state via get_state without deadlocking.
        self._lock = threading.RLock()

    def register(self, observer):
        with self._lock:
            if observer not in self.observers:
                self.observers.append(observer)

    def unregister(self, observer):
        with self._lock:
            try:
                self.observers.remove(observer)
            except ValueError:
                pass

    def notify(self):
        # Snapshot the state + observer list under the lock so concurrent
        # set_state / register / unregister calls cannot corrupt iteration or
        # hand observers a partially-updated state.
        with self._lock:
            state = self.state
            observers_snapshot = list(self.observers)
        for observer in observers_snapshot:
            observer.update(state)

    def set_state(self, state):
        # Pass the new state explicitly to observers instead of relying on
        # self.state — otherwise two racing senders can stomp self.state
        # between the assignment and the notify loop, causing observers to
        # see the wrong value.
        with self._lock:
            self.state = state
            observers_snapshot = list(self.observers)
        for observer in observers_snapshot:
            observer.update(state)

    def get_state(self):
        with self._lock:
            return self.state
