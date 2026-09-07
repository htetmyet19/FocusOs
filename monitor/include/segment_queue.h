#pragma once

#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <optional>
#include <queue>
#include <utility>

#include "segment.h"

class SegmentQueue {
public:
    // Adds a completed segment to the queue.
    // Returns false if the queue has already been closed.
    bool push(Segment segment) {
        {
            std::lock_guard<std::mutex> lock(mutex_);

            if (closed_) {
                return false;
            }

            queue_.push(std::move(segment));
        }

        condition_.notify_one();
        return true;
    }

    // Waits until a segment exists or the queue closes.
    // Returns nullopt only when the queue is closed and empty.
    std::optional<Segment> waitAndPop() {
        std::unique_lock<std::mutex> lock(mutex_);

        condition_.wait(lock, [this] {
            return closed_ || !queue_.empty();
        });

        if (queue_.empty()) {
            return std::nullopt;
        }

        Segment segment = std::move(queue_.front());
        queue_.pop();

        return segment;
    }

    // Stops accepting new segments.
    // Existing segments remain available for the writer to process.
    void close() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            closed_ = true;
        }

        condition_.notify_all();
    }

    bool isClosed() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return closed_;
    }

    std::size_t size() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return queue_.size();
    }

private:
    mutable std::mutex mutex_;
    std::condition_variable condition_;
    std::queue<Segment> queue_;
    bool closed_ = false;
};