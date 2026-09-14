from learning.runnable.runnable import AppRunnable, on_init, on_start, on_end


class AppTesting(AppRunnable):

    @on_init
    def on_testing_init(self):
        pass

    @on_start
    def on_testing_start(self):
        pass

    @on_end
    def on_testing_end(self):
        pass
