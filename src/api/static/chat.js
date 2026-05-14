/**
 * Issue Pipeline — 채팅 UI
 *
 * 담당:
 *   - 세션 목록 로드 / 생성 / 선택
 *   - 메시지 로드 및 렌더링 (marked.js Markdown)
 *   - SSE 스트리밍 질문 처리
 *   - 피드백(thumbs up/down) 전송
 */

// ── 상태 ──────────────────────────────────────────
let currentSessionId = null;
let isStreaming = false;

// ── DOM ───────────────────────────────────────────
const sessionList   = document.getElementById('sessionList');
const newChatBtn    = document.getElementById('newChatBtn');
const chatHeader    = document.getElementById('chatHeader');
const messagesWrap  = document.getElementById('messagesWrap');
const emptyState    = document.getElementById('emptyState');
const questionInput = document.getElementById('questionInput');
const sendBtn       = document.getElementById('sendBtn');

// ── 초기화 ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSessions();
  newChatBtn.addEventListener('click', createSession);
  sendBtn.addEventListener('click', handleSend);
  questionInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
  questionInput.addEventListener('input', autoResizeTextarea);
});

// ── API 헬퍼 ──────────────────────────────────────
async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API 오류 ${res.status}: ${path}`);
  return res;
}

// ── 세션 ─────────────────────────────────────────

async function loadSessions() {
  try {
    const res = await apiFetch('/api/v1/chat/sessions?limit=50');
    const sessions = await res.json();
    renderSessionList(sessions);
  } catch (e) {
    console.error('세션 로드 실패:', e);
  }
}

async function createSession() {
  try {
    const res = await apiFetch('/api/v1/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: '' }),
    });
    const session = await res.json();
    await loadSessions();
    selectSession(session.id, session.title);
  } catch (e) {
    console.error('세션 생성 실패:', e);
  }
}

async function selectSession(id, title) {
  currentSessionId = id;

  // 사이드바 활성 표시
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  chatHeader.textContent = title || '새 대화';
  enableInput();
  await loadMessages(id);
}

// ── 메시지 ────────────────────────────────────────

async function loadMessages(sessionId) {
  clearMessages();
  try {
    const res = await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages`);
    const messages = await res.json();
    if (messages.length === 0) {
      showEmptyState();
      return;
    }
    hideEmptyState();
    messages.forEach(msg => appendMessage(msg.role, msg.content, msg.id, msg.feedback));
    scrollToBottom();
  } catch (e) {
    console.error('메시지 로드 실패:', e);
  }
}

// ── 전송 ──────────────────────────────────────────

async function handleSend() {
  if (isStreaming || !currentSessionId) return;
  const question = questionInput.value.trim();
  if (!question) return;

  questionInput.value = '';
  autoResizeTextarea();
  disableInput();
  hideEmptyState();

  appendMessage('user', question);
  scrollToBottom();

  await streamAnswer(question);
  enableInput();
  questionInput.focus();
}

async function streamAnswer(question) {
  isStreaming = true;
  const { el: streamEl, textEl } = appendStreamingMessage();
  scrollToBottom();

  let fullText = '';
  let doneData = null;

  try {
    const res = await fetch(`/api/v1/chat/sessions/${currentSessionId}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 5 }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop(); // 마지막 미완성 줄은 버퍼에 보관

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const event = JSON.parse(line.slice(6));

        if (event.type === 'text') {
          fullText += event.text;
          textEl.innerHTML = marked.parse(fullText);
          scrollToBottom();
        } else if (event.type === 'done') {
          doneData = event;
        } else if (event.type === 'error') {
          textEl.textContent = `오류: ${event.detail}`;
        }
      }
    }
  } catch (e) {
    textEl.textContent = `연결 오류: ${e.message}`;
  }

  // 스트리밍 커서 제거
  streamEl.classList.remove('streaming-cursor');

  // 피드백 버튼 추가
  if (doneData?.message_id) {
    appendFeedbackButtons(streamEl, doneData.message_id);
    // 세션 제목 갱신 (첫 메시지에서 자동 변경될 수 있음)
    refreshSessionTitle();
  }

  isStreaming = false;
}

// ── UI 렌더링 ─────────────────────────────────────

function renderSessionList(sessions) {
  sessionList.innerHTML = '';
  if (sessions.length === 0) {
    sessionList.innerHTML = '<p style="color:#475569;font-size:.8rem;padding:.75rem;text-align:center;">세션이 없습니다</p>';
    return;
  }
  sessions.forEach(s => {
    const el = document.createElement('div');
    el.className = 'session-item' + (s.id === currentSessionId ? ' active' : '');
    el.dataset.id = s.id;
    const date = new Date(s.updated_at).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    el.innerHTML = `<span>${escapeHtml(s.title)}</span><span class="session-date">${date}</span>`;
    el.addEventListener('click', () => selectSession(s.id, s.title));
    sessionList.appendChild(el);
  });
}

function appendMessage(role, content, msgId = null, feedback = null) {
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;
  if (msgId) row.dataset.msgId = msgId;

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? '나' : 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';

  if (role === 'assistant') {
    bubble.innerHTML = marked.parse(content);
    if (msgId) appendFeedbackButtons(bubble, msgId, feedback);
  } else {
    bubble.textContent = content;
  }

  row.appendChild(avatar);
  row.appendChild(bubble);
  messagesWrap.appendChild(row);
  return bubble;
}

function appendStreamingMessage() {
  const row = document.createElement('div');
  row.className = 'msg-row assistant';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble streaming-cursor';

  const textEl = document.createElement('div');
  bubble.appendChild(textEl);
  row.appendChild(avatar);
  row.appendChild(bubble);
  messagesWrap.appendChild(row);
  return { el: bubble, textEl };
}

function appendFeedbackButtons(parentEl, msgId, currentFeedback = null) {
  // 기존 피드백 영역 제거 (중복 방지)
  const existing = parentEl.querySelector('.feedback-row');
  if (existing) existing.remove();

  const row = document.createElement('div');
  row.className = 'feedback-row';

  [['thumbs_up', '👍'], ['thumbs_down', '👎']].forEach(([value, label]) => {
    const btn = document.createElement('button');
    btn.className = 'feedback-btn' + (currentFeedback === value ? ' active' : '');
    btn.textContent = label;
    btn.title = value === 'thumbs_up' ? '도움이 됐어요' : '개선이 필요해요';
    btn.addEventListener('click', async () => {
      const isSame = btn.classList.contains('active');
      const newFeedback = isSame ? null : value;
      await sendFeedback(currentSessionId, msgId, newFeedback);
      row.querySelectorAll('.feedback-btn').forEach(b => b.classList.remove('active'));
      if (!isSame) btn.classList.add('active');
    });
    row.appendChild(btn);
  });

  parentEl.appendChild(row);
}

// ── 피드백 ────────────────────────────────────────

async function sendFeedback(sessionId, messageId, feedback) {
  try {
    await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages/${messageId}/feedback`, {
      method: 'PATCH',
      body: JSON.stringify({ feedback }),
    });
  } catch (e) {
    console.error('피드백 전송 실패:', e);
  }
}

// ── 유틸 ──────────────────────────────────────────

async function refreshSessionTitle() {
  if (!currentSessionId) return;
  try {
    const res = await apiFetch(`/api/v1/chat/sessions/${currentSessionId}`);
    const session = await res.json();
    chatHeader.textContent = session.title;
    await loadSessions();
  } catch (e) { /* 무시 */ }
}

function clearMessages() {
  messagesWrap.innerHTML = '';
  const empty = document.createElement('div');
  empty.className = 'empty-state';
  empty.id = 'emptyState';
  empty.innerHTML = '<span class="empty-icon">💬</span><p>왼쪽에서 세션을 선택하거나 새 대화를 시작하세요.</p>';
  messagesWrap.appendChild(empty);
}

function showEmptyState() {
  const el = document.getElementById('emptyState');
  if (el) el.style.display = '';
}

function hideEmptyState() {
  const el = document.getElementById('emptyState');
  if (el) el.style.display = 'none';
}

function enableInput() {
  questionInput.disabled = false;
  sendBtn.disabled = false;
}

function disableInput() {
  questionInput.disabled = true;
  sendBtn.disabled = true;
}

function scrollToBottom() {
  messagesWrap.scrollTop = messagesWrap.scrollHeight;
}

function autoResizeTextarea() {
  questionInput.style.height = 'auto';
  questionInput.style.height = Math.min(questionInput.scrollHeight, 160) + 'px';
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
