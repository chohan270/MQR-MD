/**
 * Ordered, per-target forwarding queues.
 *
 * Each target has its own FIFO worker. This keeps message order stable for a
 * target while allowing several target groups to receive the same burst in
 * parallel. Failed deliveries stay in that target's queue and are retried.
 */
class OrderedForwardQueue {
    constructor(options = {}) {
        this.maxRetries = options.maxRetries ?? Infinity;
        this.retryDelayMs = options.retryDelayMs ?? 1000;
        this.workers = new Map();
        this.sequence = 0;
    }

    enqueue(target, message, send) {
        if (!target || typeof send !== 'function') return;

        let worker = this.workers.get(target);
        if (!worker) {
            worker = { pending: [], running: false, sent: 0, failed: 0 };
            this.workers.set(target, worker);
        }

        worker.pending.push({ id: ++this.sequence, message, send, attempts: 0 });
        this.run(target, worker).catch((error) => {
            console.error(`[FORWARD-QUEUE] worker failed for ${target}:`, error.message);
        });
    }

    async run(target, worker) {
        if (worker.running) return;
        worker.running = true;

        try {
            while (worker.pending.length) {
                const item = worker.pending[0];
                try {
                    await item.send(item.message);
                    worker.pending.shift();
                    worker.sent++;
                } catch (error) {
                    item.attempts++;
                    worker.failed++;
                    if (item.attempts > this.maxRetries) {
                        console.error(`[FORWARD-QUEUE] dropped after retries for ${target}:`, error.message);
                        worker.pending.shift();
                        continue;
                    }

                    const delay = this.retryDelayMs * Math.min(item.attempts, 5);
                    console.error(`[FORWARD-QUEUE] retry ${item.attempts}/${this.maxRetries} for ${target}:`, error.message);
                    await new Promise((resolve) => setTimeout(resolve, delay));
                }
            }
        } finally {
            worker.running = false;
            if (!worker.pending.length) this.workers.delete(target);
        }
    }

    stats() {
        let pending = 0;
        let activeTargets = 0;
        for (const worker of this.workers.values()) {
            pending += worker.pending.length;
            if (worker.running) activeTargets++;
        }
        return { pending, activeTargets };
    }
}

module.exports = OrderedForwardQueue;