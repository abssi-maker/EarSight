"""
Thin Confluent Kafka producer/consumer wrapper.

Handles connection, retry, and dead-letter topic publishing.
All services import get_producer() / get_consumer() from here.
"""

import json
import os
import time
from typing import Any, Callable, Optional

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from dotenv import load_dotenv

load_dotenv()

_DEAD_LETTER_TOPIC = "earsight.dead-letter"


def _base_config() -> dict:
    return {
        "bootstrap.servers": os.environ["CONFLUENT_BOOTSTRAP_SERVERS"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "PLAIN",
        "sasl.username": os.environ["CONFLUENT_API_KEY"],
        "sasl.password": os.environ["CONFLUENT_API_SECRET"],
    }


def get_producer() -> Producer:
    """Return a configured Confluent Producer."""
    cfg = _base_config()
    cfg["acks"] = "all"
    cfg["retries"] = 5
    cfg["retry.backoff.ms"] = 500
    return Producer(cfg)


def get_consumer(group_id: str, topics: list[str]) -> Consumer:
    """Return a configured Confluent Consumer subscribed to *topics*."""
    cfg = _base_config()
    cfg.update({
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer = Consumer(cfg)
    consumer.subscribe(topics)
    return consumer


def publish(producer: Producer, topic: str, value: dict, key: Optional[str] = None) -> None:
    """Serialize *value* as JSON and produce to *topic*. Blocks until delivered."""
    producer.produce(
        topic=topic,
        value=json.dumps(value).encode(),
        key=key.encode() if key else None,
    )
    producer.flush(timeout=10)


def dead_letter(producer: Producer, original_topic: str, message: Any, reason: str) -> None:
    """Send a failed message to the dead-letter topic with metadata."""
    payload = {
        "original_topic": original_topic,
        "reason": reason,
        "message": message,
        "ts": time.time(),
    }
    publish(producer, _DEAD_LETTER_TOPIC, payload)


def consume_loop(
    consumer: Consumer,
    handler: Callable[[dict], None],
    producer: Optional[Producer] = None,
    source_topic: str = "",
    poll_timeout: float = 1.0,
) -> None:
    """
    Poll *consumer* indefinitely, calling *handler* for each message.

    On handler failure, if *producer* and *source_topic* are provided the message
    is forwarded to the dead-letter topic and processing continues.
    """
    try:
        while True:
            msg = consumer.poll(timeout=poll_timeout)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(msg.error())
            try:
                value = json.loads(msg.value().decode())
                handler(value)
            except Exception as exc:
                print(f"[kafka] handler error on {source_topic}: {exc}")
                if producer and source_topic:
                    try:
                        dead_letter(producer, source_topic, msg.value().decode(), str(exc))
                    except Exception:
                        pass
    finally:
        consumer.close()
