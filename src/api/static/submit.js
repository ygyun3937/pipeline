function selectDomain(domain) {
  document.getElementById('domainInput').value = domain;

  document.querySelectorAll('.domain-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.domain === domain);
  });

  const isBattery = domain === 'battery';
  document.getElementById('batteryFields').classList.toggle('hidden', !isBattery);
  document.getElementById('softwareFields').classList.toggle('hidden', isBattery);

  // 비활성 필드 required 해제 (폼 유효성 검사 우회 방지)
  document.querySelectorAll('#batteryFields input, #batteryFields select').forEach(el => {
    el.disabled = !isBattery;
  });
  document.querySelectorAll('#softwareFields input').forEach(el => {
    el.disabled = isBattery;
  });
}

// 초기 상태 설정
document.addEventListener('DOMContentLoaded', () => {
  const current = document.getElementById('domainInput').value || 'battery';
  selectDomain(current);
});
