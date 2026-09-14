from threading import Event


# Define the custom event class
class MessageEvent(Event):
    def __init__(self, message):
        super().__init__()  # call the parent class constructor
        self.message = message  # the message attribute

    def get_message(self):
        return self.message  # the get_message method