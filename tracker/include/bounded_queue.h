#pragma once
// Bounded blocking queue: the classic producer/consumer "bounded buffer".
//
//   producers --push()--> [ item | item | ... capacity ] --pop()--> consumer
//
// Synchronisation:
//   * mutex_     gives mutual exclusion over the deque (the critical section)
//   * notFull_   producers wait on it while the buffer is full
//   * notEmpty_  the consumer waits on it while the buffer is empty
// Waiting on a condition variable releases the mutex, so a blocked thread
// costs no CPU (no busy waiting). Predicates guard against spurious wake-ups.
//
// close() lets the consumer drain what is left and then stop.

#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <optional>
#include <utility>

namespace ft {

template <typename T>
class BoundedQueue {
public:
    explicit BoundedQueue(std::size_t capacity) : capacity_(capacity ? capacity : 1) {}

    // Blocks while the buffer is full. Returns false if the queue is closed.
    bool push(T item) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (queue_.size() >= capacity_ && !closed_) ++producerWaits_;   // back-pressure
        notFull_.wait(lock, [this] { return closed_ || queue_.size() < capacity_; });
        if (closed_) return false;

        queue_.push_back(std::move(item));
        if (queue_.size() > maxDepth_) maxDepth_ = queue_.size();
        lock.unlock();              // notify after unlocking: the woken thread can run at once
        notEmpty_.notify_one();
        return true;
    }

    // Blocks while the buffer is empty. Returns nullopt only when closed AND empty.
    std::optional<T> pop() {
        std::unique_lock<std::mutex> lock(mutex_);
        notEmpty_.wait(lock, [this] { return closed_ || !queue_.empty(); });
        if (queue_.empty()) return std::nullopt;

        T item = std::move(queue_.front());
        queue_.pop_front();
        lock.unlock();
        notFull_.notify_one();
        return item;
    }

    void close() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            closed_ = true;
        }
        notFull_.notify_all();
        notEmpty_.notify_all();
    }

    std::size_t size() const          { std::lock_guard<std::mutex> l(mutex_); return queue_.size(); }
    std::size_t capacity() const      { return capacity_; }
    std::size_t maxDepth() const      { std::lock_guard<std::mutex> l(mutex_); return maxDepth_; }
    std::uint64_t producerWaits() const { std::lock_guard<std::mutex> l(mutex_); return producerWaits_; }

private:
    const std::size_t       capacity_;
    mutable std::mutex      mutex_;
    std::condition_variable notFull_;
    std::condition_variable notEmpty_;
    std::deque<T>           queue_;
    bool                    closed_        = false;
    std::size_t             maxDepth_      = 0;
    std::uint64_t           producerWaits_ = 0;
};

} // namespace ft
