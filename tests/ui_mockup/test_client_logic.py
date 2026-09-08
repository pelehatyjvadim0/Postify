from tests.ui_mockup.browser_support import install_api


def test_api_client_sends_csrf_on_mutation_and_hides_upstream_error(page_factory, base_url):
    page = page_factory(); install_api(page); page.goto(base_url)
    result = page.evaluate("""async () => {
      const calls=[]; window.fetch=async (url, options={}) => { calls.push({url, headers:[...new Headers(options.headers||{}).entries()]}); if(url.endsWith('/bootstrap')) return new Response(JSON.stringify({csrfToken:'token'})); return new Response('secret', {status:502}); };
      const api=await import('/api.js'); await api.getBootstrap(); try { await api.request('/mutate',{method:'POST'}); } catch(error) { return {calls,error:{code:error.code,message:error.message}}; }
    }""")
    mutation = next(call for call in result["calls"] if call["url"].endswith("/mutate"))
    assert ["x-postify-csrf", "token"] in mutation["headers"]
    assert result["error"] == {"code": "request_failed", "message": "request_failed"}


def test_provider_markup_and_workspace_titles_escape_untrusted_values(page_factory, base_url):
    page = page_factory(); install_api(page); page.goto(base_url)
    result = page.evaluate("""async () => {
      const {renderProviderConfiguration}=await import('/settings.js'); const {shortTitle}=await import('/workspace.js');
      return {markup:renderProviderConfiguration({sources:[{code:'x',fields:[{name:'id',label:'<img>',type:'text',required:true}]}]},'sources','x',{}), title:shortTitle('<img src=x>')};
    }""")
    assert "&lt;img&gt;" in result["markup"]
    assert result["title"] == "<img src=x>"
