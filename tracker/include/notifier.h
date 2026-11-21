#pragma once
// Notifier: Windows notifications ("Discord was closed. You're focusing.").
//
// A notification needs a tray icon, a tray icon needs a window, and a window
// needs a thread that runs a message loop. So the notifier owns its own
// thread (thread 4) with a hidden window and its own Windows message queue.
//
// Other threads call notify(): the text goes into a mutex-protected queue and
// PostMessage wakes the notifier thread, which shows it. PostMessage never
// blocks the caller, so the sampler loop is never slowed down by the UI.

#include <atomic>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <utility>

namespace ft {

class Notifier {
public:
    Notifier() = default;
    ~Notifier();
    Notifier(const Notifier&) = delete;
    Notifier& operator=(const Notifier&) = delete;

    void start(const std::string& tooltip);           // creates thread, window and tray icon
    void notify(const std::string& title, const std::string& text);   // UTF-8, thread-safe
    void stop();                                      // removes the icon, ends the thread

    // Called on the notifier thread by its window procedure: shows the newest
    // pending message. Not for use from other threads.
    void showPending(void* hwnd);

private:
    void run(std::string tooltip);

    std::thread       thread_;
    std::atomic<void*> hwnd_{nullptr};                // HWND of the hidden window
    std::mutex        mutex_;
    std::deque<std::pair<std::string, std::string>> pending_;
    std::atomic<bool> ready_{false};
};

} // namespace ft
