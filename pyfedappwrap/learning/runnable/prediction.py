from learning.runnable.runnable import AppRunnable, on_start, on_end, on_init


class AppPrediction(AppRunnable):

    @on_init
    def on_prediction_init(self):
        pass

    @on_start
    def on_prediction_start(self):
        pass

    @on_end
    def on_prediction_end(self):
        pass

