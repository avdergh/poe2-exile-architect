(() => {
  const data = JSON.parse(document.getElementById('entity-data').textContent);
  const search = document.getElementById('guide-search');
  const sections = [...document.querySelectorAll('.learning-section')];
  const links = [...document.querySelectorAll('nav [data-section]')];
  const modal = document.getElementById('entity-dialog');
  let returnFocus = null;
  function filter() {
    const query = search.value.trim().toLocaleLowerCase();
    let count = 0;
    sections.forEach(section => {
      const visible = !query || section.textContent.toLocaleLowerCase().includes(query);
      section.hidden = !visible;
      links.find(link => link.dataset.section === section.id).hidden = !visible;
      if (visible) count++;
    });
    document.getElementById('no-results').hidden = count > 0;
  }
  function clear() { search.value = ''; filter(); }
  search.addEventListener('input', filter);
  document.getElementById('clear-search').addEventListener('click', () => { clear(); search.focus(); });
  document.getElementById('show-all').addEventListener('click', clear);
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-entity]');
    if (!trigger) return;
    const entry = data[trigger.dataset.entity];
    if (!entry) return;
    if (!modal.open) returnFocus = trigger;
    document.getElementById('entity-name').textContent = trigger.querySelector('.entity-label')?.textContent || entry.name;
    document.getElementById('entity-kind').textContent = entry.category;
    document.getElementById('entity-caption').textContent = entry.caption;
    const art = document.getElementById('detail-icon');
    art.toggleAttribute('hidden', !entry.icon);
    if (entry.icon) art.querySelector('use').setAttribute('href', '#' + entry.icon);
    document.getElementById('entity-description').innerHTML = entry.description;
    const jump = document.getElementById('entity-jump');
    jump.hidden = !entry.section;
    if (entry.section) jump.href = '#' + entry.section;
    if (!modal.open) modal.showModal();
  });
  document.getElementById('close-dialog').addEventListener('click', () => modal.close());
  document.getElementById('entity-jump').addEventListener('click', () => { clear(); modal.close(); });
  modal.addEventListener('close', () => { if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true }); });
  modal.addEventListener('click', event => { if (event.target === modal) { const r = modal.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) modal.close(); } });
  if (window.matchMedia('(max-width:720px)').matches) document.querySelector('.sidebar details').open = false;
  links.forEach(link => link.addEventListener('click', () => { if (window.matchMedia('(max-width:720px)').matches) document.querySelector('.sidebar details').open = false; }));
  const observer = new IntersectionObserver(entries => {
    const current = entries.find(entry => entry.isIntersecting);
    if (current) links.forEach(link => link.classList.toggle('active', link.dataset.section === current.target.id));
  }, { rootMargin: '-12% 0px -65% 0px' });
  sections.forEach(section => observer.observe(section));
})();
