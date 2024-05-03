import re

from ..bbot_fixtures import *


@pytest.mark.asyncio
async def test_web_engine(bbot_scanner, bbot_httpserver):

    url = bbot_httpserver.url_for("/test")
    bbot_httpserver.expect_request(uri="/test").respond_with_data("hello_there")

    scan = bbot_scanner()

    # request
    response = await scan.helpers.request(url)
    assert response.status_code > 0
    assert response.text == "hello_there"

    # request_batch
    responses = [r async for r in scan.helpers.request_batch([url] * 100)]
    assert len(responses) == 100
    assert all([r[0] == url for r in responses])
    assert all([r[1].status_code > 0 and r[1].text == "hello_there" for r in responses])

    # download
    filename = await scan.helpers.download(url)
    file_content = open(filename).read()
    assert file_content == "hello_there"


@pytest.mark.asyncio
async def test_web_helpers(bbot_scanner, bbot_httpserver):
    scan1 = bbot_scanner("8.8.8.8")
    scan2 = bbot_scanner("127.0.0.1")

    user_agent = CORE.config.get("user_agent", "")
    headers = {"User-Agent": user_agent}
    custom_headers = CORE.config.get("http_headers", {})
    headers.update(custom_headers)
    assert headers["test"] == "header"

    url = bbot_httpserver.url_for("/test_http_helpers")
    # test user agent + custom headers
    bbot_httpserver.expect_request(uri="/test_http_helpers", headers=headers).respond_with_data(
        "test_http_helpers_yep"
    )
    response = await scan1.helpers.request(url)
    # should fail because URL is not in-scope
    assert response.status_code == 500
    response = await scan2.helpers.request(url)
    # should succeed because URL is in-scope
    assert response.status_code == 200
    assert response.text == "test_http_helpers_yep"

    # download file
    path = "/test_http_helpers_download"
    url = bbot_httpserver.url_for(path)
    download_content = "test_http_helpers_download_yep"
    bbot_httpserver.expect_request(uri=path).respond_with_data(download_content)
    filename = await scan1.helpers.download(url)
    assert Path(str(filename)).is_file()
    assert scan1.helpers.is_cached(url)
    with open(filename) as f:
        assert f.read() == download_content
    filename = Path("/tmp/bbot_download_test_file")
    filename.unlink(missing_ok=True)
    filename2 = await scan1.helpers.download(url, filename=filename)
    assert filename2 == filename
    assert filename2.is_file()
    with open(filename2) as f:
        assert f.read() == download_content

    # beautifulsoup
    download_content = """
    <div>
    <h1>Example Domain</h1>
    <p>This domain is for use in illustrative examples in documents. You may use this
    domain in literature without prior coordination or asking for permission.</p>
    <p><a href="https://www.iana.org/domains/example">More information...</a></p>
    </div>
    """

    path = "/test_http_helpers_beautifulsoup"
    url = bbot_httpserver.url_for(path)
    bbot_httpserver.expect_request(uri=path).respond_with_data(download_content, status=200)
    webpage = await scan1.helpers.request(url)
    assert webpage, f"Webpage is False"
    soup = scan1.helpers.beautifulsoup(webpage, "html.parser")
    assert soup, f"Soup is False"
    # pretty_print = soup.prettify()
    # assert pretty_print, f"PrettyPrint is False"
    # scan1.helpers.log.info(f"{pretty_print}")
    html_text = soup.find(text="Example Domain")
    assert html_text, f"Find HTML Text is False"

    # 404
    path = "/test_http_helpers_download_404"
    url = bbot_httpserver.url_for(path)
    download_content = "404"
    bbot_httpserver.expect_request(uri=path).respond_with_data(download_content, status=404)
    filename = await scan1.helpers.download(url)
    assert filename is None
    assert not scan1.helpers.is_cached(url)

    # wordlist
    path = "/test_http_helpers_wordlist"
    url = bbot_httpserver.url_for(path)
    download_content = "a\ncool\nword\nlist"
    bbot_httpserver.expect_request(uri=path).respond_with_data(download_content)
    filename = await scan1.helpers.wordlist(url)
    assert Path(str(filename)).is_file()
    assert scan1.helpers.is_cached(url)
    assert list(scan1.helpers.read_file(filename)) == ["a", "cool", "word", "list"]

    # page iteration
    base_path = "/test_http_page_iteration"
    template_path = base_path + "/{page}?page_size={page_size}&offset={offset}"
    template_url = bbot_httpserver.url_for(template_path)
    bbot_httpserver.expect_request(
        uri=f"{base_path}/1", query_string={"page_size": "100", "offset": "0"}
    ).respond_with_data("page1")
    bbot_httpserver.expect_request(
        uri=f"{base_path}/2", query_string={"page_size": "100", "offset": "100"}
    ).respond_with_data("page2")
    bbot_httpserver.expect_request(
        uri=f"{base_path}/3", query_string={"page_size": "100", "offset": "200"}
    ).respond_with_data("page3")
    results = []
    agen = scan1.helpers.api_page_iter(template_url)
    try:
        async for result in agen:
            if result and result.text.startswith("page"):
                results.append(result)
            else:
                break
    finally:
        await agen.aclose()
    assert not results
    agen = scan1.helpers.api_page_iter(template_url, json=False)
    try:
        async for result in agen:
            if result and result.text.startswith("page"):
                results.append(result)
            else:
                break
    finally:
        await agen.aclose()
    assert [r.text for r in results] == ["page1", "page2", "page3"]


@pytest.mark.asyncio
async def test_web_interactsh(bbot_scanner, bbot_httpserver):
    from bbot.core.helpers.interactsh import server_list

    sync_called = False
    async_called = False

    sync_correct_url = False
    async_correct_url = False

    scan1 = bbot_scanner("8.8.8.8")
    scan1.status = "RUNNING"

    interactsh_client = scan1.helpers.interactsh(poll_interval=3)
    interactsh_client2 = scan1.helpers.interactsh(poll_interval=3)

    async def async_callback(data):
        nonlocal async_called
        nonlocal async_correct_url
        async_called = True
        d = data.get("raw-request", "")
        async_correct_url |= "bbot_interactsh_test" in d
        log.debug(f"interactsh poll (async): {d}")

    def sync_callback(data):
        nonlocal sync_called
        nonlocal sync_correct_url
        sync_called = True
        d = data.get("raw-request", "")
        sync_correct_url |= "bbot_interactsh_test" in d
        log.debug(f"interactsh poll (sync): {d}")

    interactsh_domain = await interactsh_client.register(callback=async_callback)
    url = f"http://{interactsh_domain}/bbot_interactsh_test"
    response = await scan1.helpers.request(url)
    assert response.status_code == 200
    assert any(interactsh_domain.endswith(f"{s}") for s in server_list)

    interactsh_domain2 = await interactsh_client2.register(callback=sync_callback)
    url2 = f"http://{interactsh_domain2}/bbot_interactsh_test"
    response2 = await scan1.helpers.request(url2)
    assert response2.status_code == 200
    assert any(interactsh_domain2.endswith(f"{s}") for s in server_list)

    await asyncio.sleep(10)

    data_list = await interactsh_client.poll()
    data_list2 = await interactsh_client2.poll()
    assert isinstance(data_list, list)
    assert isinstance(data_list2, list)

    assert await interactsh_client.deregister() is None
    assert await interactsh_client2.deregister() is None

    assert sync_called, "Interactsh synchrononous callback was not called"
    assert async_called, "Interactsh async callback was not called"

    assert sync_correct_url, f"Data content was not correct for {url2}"
    assert async_correct_url, f"Data content was not correct for {url}"


@pytest.mark.asyncio
async def test_web_curl(bbot_scanner, bbot_httpserver):
    scan = bbot_scanner("127.0.0.1")
    helpers = scan.helpers
    url = bbot_httpserver.url_for("/curl")
    bbot_httpserver.expect_request(uri="/curl").respond_with_data("curl_yep")
    bbot_httpserver.expect_request(uri="/index.html").respond_with_data("curl_yep_index")
    assert await helpers.curl(url=url) == "curl_yep"
    assert await helpers.curl(url=url, ignore_bbot_global_settings=True) == "curl_yep"
    assert (await helpers.curl(url=url, head_mode=True)).startswith("HTTP/")
    assert await helpers.curl(url=url, raw_body="body") == "curl_yep"
    assert (
        await helpers.curl(
            url=url,
            raw_path=True,
            headers={"test": "test", "test2": ["test2"]},
            ignore_bbot_global_settings=False,
            post_data={"test": "test"},
            method="POST",
            cookies={"test": "test"},
            path_override="/index.html",
        )
        == "curl_yep_index"
    )
    # test custom headers
    bbot_httpserver.expect_request("/test-custom-http-headers-curl", headers={"test": "header"}).respond_with_data(
        "curl_yep_headers"
    )
    headers_url = bbot_httpserver.url_for("/test-custom-http-headers-curl")
    curl_result = await helpers.curl(url=headers_url)
    assert curl_result == "curl_yep_headers"


@pytest.mark.asyncio
async def test_web_http_compare(httpx_mock, helpers):
    httpx_mock.add_response(url=re.compile(r"http://www\.example\.com.*"), text="wat")
    compare_helper = helpers.http_compare("http://www.example.com")
    await compare_helper.compare("http://www.example.com", headers={"asdf": "asdf"})
    await compare_helper.compare("http://www.example.com", cookies={"asdf": "asdf"})
    await compare_helper.compare("http://www.example.com", check_reflection=True)
    compare_helper.compare_body({"asdf": "fdsa"}, {"fdsa": "asdf"})
    for mode in ("getparam", "header", "cookie"):
        assert await compare_helper.canary_check("http://www.example.com", mode=mode) == True


@pytest.mark.asyncio
async def test_http_proxy(bbot_scanner, bbot_httpserver, proxy_server):
    endpoint = "/test_http_proxy"
    url = bbot_httpserver.url_for(endpoint)
    # test user agent + custom headers
    bbot_httpserver.expect_request(uri=endpoint).respond_with_data("test_http_proxy_yep")

    proxy_address = f"http://127.0.0.1:{proxy_server.server_address[1]}"

    scan = bbot_scanner("127.0.0.1", config={"http_proxy": proxy_address})

    assert len(proxy_server.RequestHandlerClass.urls) == 0

    r = await scan.helpers.request(url)

    assert (
        len(proxy_server.RequestHandlerClass.urls) == 1
    ), f"Request to {url} did not go through proxy {proxy_address}"
    visited_url = proxy_server.RequestHandlerClass.urls[0]
    assert visited_url.endswith(endpoint), f"There was a problem with request to {url}: {visited_url}"
    assert r.status_code == 200 and r.text == "test_http_proxy_yep"


@pytest.mark.asyncio
async def test_http_ssl(bbot_scanner, bbot_httpserver_ssl):
    endpoint = "/test_http_ssl"
    url = bbot_httpserver_ssl.url_for(endpoint)
    # test user agent + custom headers
    bbot_httpserver_ssl.expect_request(uri=endpoint).respond_with_data("test_http_ssl_yep")

    scan1 = bbot_scanner("127.0.0.1", config={"ssl_verify": True, "http_debug": True})

    scan2 = bbot_scanner("127.0.0.1", config={"ssl_verify": False, "http_debug": True})

    r1 = await scan1.helpers.request(url)
    assert r1 is None, "Request to self-signed SSL server went through even with ssl_verify=True"
    r2 = await scan2.helpers.request(url)
    assert r2 is not None, "Request to self-signed SSL server failed even with ssl_verify=False"
    assert r2.status_code == 200 and r2.text == "test_http_ssl_yep"


@pytest.mark.asyncio
async def test_web_cookies(bbot_scanner, httpx_mock):
    import httpx

    # make sure cookies work when enabled
    httpx_mock.add_response(url="http://www.evilcorp.com/cookies", headers=[("set-cookie", "wat=asdf; path=/")])
    scan = bbot_scanner()
    client = scan.helpers.AsyncClient(persist_cookies=True)
    r = await client.get(url="http://www.evilcorp.com/cookies")
    assert r.cookies["wat"] == "asdf"
    httpx_mock.add_response(url="http://www.evilcorp.com/cookies/test", match_headers={"Cookie": "wat=asdf"})
    r = await client.get(url="http://www.evilcorp.com/cookies/test")
    # make sure we can manually send cookies
    httpx_mock.add_response(url="http://www.evilcorp.com/cookies/test2", match_headers={"Cookie": "asdf=wat"})
    r = await scan.helpers.request(url="http://www.evilcorp.com/cookies/test2", cookies={"asdf": "wat"})
    assert client.cookies["wat"] == "asdf"

    # make sure they don't when they're not
    httpx_mock.add_response(url="http://www2.evilcorp.com/cookies", headers=[("set-cookie", "wats=fdsa; path=/")])
    scan = bbot_scanner()
    client2 = scan.helpers.AsyncClient(persist_cookies=False)
    r = await client2.get(url="http://www2.evilcorp.com/cookies")
    # make sure we can access the cookies
    assert "wats" in r.cookies
    httpx_mock.add_response(url="http://www2.evilcorp.com/cookies/test", match_headers={"Cookie": "wats=fdsa"})
    # but that they're not sent in the response
    with pytest.raises(httpx.TimeoutException):
        r = await client2.get(url="http://www2.evilcorp.com/cookies/test")
    # make sure we can manually send cookies
    httpx_mock.add_response(url="http://www2.evilcorp.com/cookies/test2", match_headers={"Cookie": "fdsa=wats"})
    r = await client2.get(url="http://www2.evilcorp.com/cookies/test2", cookies={"fdsa": "wats"})
    assert not client2.cookies
