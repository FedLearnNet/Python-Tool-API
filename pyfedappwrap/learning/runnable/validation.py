from learning.runnable.runnable import on_start, AppRunnable, on_init, on_end

class AppValidation(AppRunnable):

    @on_init
    def on_validation_init(self):
        pass

    @on_start
    def on_validation_start(self):
        pass

    @on_end
    def on_validation_end(self):
        pass
