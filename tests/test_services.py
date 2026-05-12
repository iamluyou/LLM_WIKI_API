"""测试 llm_client 和 task_queue"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.llm_client import LLMClient
from app.services.task_queue import TaskQueue, Task
from app.models.wiki import TaskResult


class TestLLMClient:
    """LLM 客户端 mock 测试"""

    def test_chat_returns_text_and_usage(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello world"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20

        with patch.object(LLMClient, "__init__", lambda self, **kwargs: None):
            client = LLMClient.__new__(LLMClient)
            client.client = MagicMock()
            client.client.chat.completions.create.return_value = mock_response
            client.model = "test-model"

            text, usage = client.chat([{"role": "user", "content": "hi"}])
            assert text == "Hello world"
            assert usage["input"] == 10
            assert usage["output"] == 20

    def test_chat_raises_on_api_error(self):
        with patch.object(LLMClient, "__init__", lambda self, **kwargs: None):
            client = LLMClient.__new__(LLMClient)
            client.client = MagicMock()
            client.client.chat.completions.create.side_effect = Exception("API error")
            client.model = "test-model"

            with pytest.raises(Exception, match="API error"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_chat_stream_yields_chunks(self):
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello"
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " world"

        with patch.object(LLMClient, "__init__", lambda self, **kwargs: None):
            client = LLMClient.__new__(LLMClient)
            client.client = MagicMock()
            client.client.chat.completions.create.return_value = iter([chunk1, chunk2])
            client.model = "test-model"

            result = list(client.chat_stream([{"role": "user", "content": "hi"}]))
            assert result == ["Hello", " world"]


class TestTask:
    def test_task_init(self):
        task = Task("task-1", ["source-a"])
        assert task.task_id == "task-1"
        assert task.source_ids == ["source-a"]
        assert task.status == "pending"
        assert task.result is None


class TestTaskQueue:
    @pytest.mark.asyncio
    async def test_submit_and_get_status(self):
        queue = TaskQueue()
        await queue.start()

        async def mock_processor(source_ids, task):
            task.progress = "done"
            return TaskResult()

        task_id = await queue.submit(["source-a"], mock_processor)
        status = queue.get_status(task_id)
        assert status is not None
        assert status.task_id == task_id

        await queue.stop()

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self):
        queue = TaskQueue()
        status = queue.get_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        queue = TaskQueue()
        task_id = await queue.submit(["source-a"], AsyncMock())
        tasks = queue.list_tasks()
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_worker_processes_task(self):
        queue = TaskQueue()
        await queue.start()

        result = TaskResult(pages_created=["test.md"])

        async def mock_processor(source_ids, task):
            return result

        task_id = await queue.submit(["source-a"], mock_processor)
        # 等待 worker 处理
        import asyncio
        await asyncio.sleep(0.5)

        status = queue.get_status(task_id)
        assert status.status == "completed"
        assert status.result.pages_created == ["test.md"]

        await queue.stop()

    @pytest.mark.asyncio
    async def test_worker_handles_failure(self):
        queue = TaskQueue()
        await queue.start()

        async def failing_processor(source_ids, task):
            raise ValueError("Processing failed")

        task_id = await queue.submit(["source-a"], failing_processor)
        import asyncio
        await asyncio.sleep(0.5)

        status = queue.get_status(task_id)
        assert status.status == "failed"

        await queue.stop()
