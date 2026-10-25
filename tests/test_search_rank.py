from mylar import search_rank


def r(name, year='2012', pub='Image', issues=10, type_='Print', cid=None):
    return {'comicname': name, 'comicyear': year, 'publisher': pub, 'issues': issues, 'type': type_, 'comicid': cid or name}


def names(rows):
    return [x['comicname'] for x in rows]


def test_split_query_pulls_out_year():
    assert search_rank.split_query('Batman (2016)') == ('batman', 2016)
    assert search_rank.split_query('The Walking Dead') == ('walking dead', None)


def test_exact_name_beats_longer_titles():
    rows = [r('Saga of the Swamp Thing', '1982', 'DC Comics', 64),
            r('Saga', '2012', 'Image', 66),
            r('Star Wars Saga', '2003', 'Dark Horse Comics', 3)]
    assert names(search_rank.rank(rows, 'saga'))[0] == 'Saga'


def test_typed_year_picks_the_right_volume():
    rows = [r('Batman', '2011', 'DC Comics', 52), r('Batman', '2016', 'DC Comics', 150), r('Batman', '1940', 'DC Comics', 713)]
    assert [x['comicyear'] for x in search_rank.rank(rows, 'Batman 2011')][0] == '2011'


def test_library_publisher_breaks_a_tie():
    rows = [r('Hulk', '2014', 'Panini', 10), r('Hulk', '2014', 'Marvel', 10)]
    assert search_rank.rank(rows, 'hulk', ['PANINI'])[0]['publisher'] == 'Panini'
    assert search_rank.rank(rows, 'hulk')[0]['publisher'] == 'Marvel'


def test_longer_run_and_print_preferred_when_names_match():
    rows = [r('Invincible', '2003', 'Image', 1, 'TPB'), r('Invincible', '2003', 'Image', 144)]
    assert search_rank.rank(rows, 'invincible')[0]['issues'] == 144


def test_punctuation_and_articles_ignored():
    assert search_rank.name_score('walking dead', 'The Walking Dead') == 1.0
    assert search_rank.name_score('x men', 'X-Men') == 1.0


def test_bad_values_dont_crash_and_order_is_stable():
    rows = [r('A', None, None, None, None, 'a'), r('A', 'None', '', 'x', None, 'b')]
    assert [x['comicid'] for x in search_rank.rank(rows, '')] == ['a', 'b']
