class Observer:
    def __init__(self, name, subject):
        self.name = name  # the name of the observer
        self.subject = subject  # the reference to the subject
        self.subject.register(self)  # register the observer to the subject

    def update(self, state):
        print(
            f"{self.name} received a notification from the subject. The new state is {state}.")  # print a message to show the response