from learning.runnable.runnable import AppRunnable, on_end, on_start, on_init


class AppTraining(AppRunnable):

    @on_init
    def on_training_init(self):
        print("Training init.")
        pass

    @on_start
    def on_training_start(self):
        print("Training start.")
        pass

    @on_end
    def on_training_end(self):
        print("Training end.")
        pass
