#ifndef CACHE_H
#define CACHE_H

#include <stdlib.h>
#include <stdio.h>

#ifdef DPDK
#include <rte_spinlock.h>
#define lock_init(x) rte_spinlock_init(x)
#define lock_lock(x) rte_spinlock_lock(x)
#define lock_unlock(x) rte_spinlock_unlock(x)
typedef rte_spinlock_t lock_t;
#else
#include <pthread.h>
#define lock_init(x) pthread_mutex_init(x, NULL)
#define lock_lock(x) pthread_mutex_lock(x)
#define lock_unlock(x) pthread_mutex_unlock(x)
typedef pthread_mutex_t lock_t;
#endif

//#define DEBUG
#define HIT_RATE
#define BUCKET_NITEMS 1

typedef struct _cache_bucket cache_bucket;

typedef struct _citem {
    struct _citem* next;
    cache_bucket* bucket;
    uint32_t hv;
    uint16_t keylen, last_vallen;
    uint8_t evicted;
    uint8_t content[];
} __attribute__((packed)) citem;

typedef struct _cache_bucket {
    citem *items[BUCKET_NITEMS];
    uint32_t hashes[BUCKET_NITEMS];
    lock_t lock;
    int replace;
} __attribute__((packed)) cache_bucket;

static inline bool citem_key_matches(citem *it, const void *key, int klen)
{
    return klen == it->keylen && !__builtin_memcmp(it->content, key, klen);
}

static inline bool citem_hkey_matches(citem *it, const void *key, int klen, uint32_t hv)
{
    return it->hv == hv && citem_key_matches(it, key, klen);
}

static inline void *citem_key(citem *it) {
    return it->content;
}

static inline void *citem_value(citem *it) {
    uint8_t *p = it->content;
    return (p + it->keylen);
}

static void cache_init(cache_bucket *buckets, int n)
{
    for (int i = 0; i < n; i++) {
        lock_init(&buckets[i].lock);
        buckets[i].replace = 0;
    }
}

static citem *cache_get(cache_bucket *buckets, int nbuckets, const void *key, int klen, uint32_t hv, bool* success)
{
#ifdef HIT_RATE
    static __thread size_t hit = 0, total = 0;
    total++;
#endif
  
    citem *it = NULL;
    size_t i;

    cache_bucket *b = buckets + (hv % nbuckets);
    lock_lock(&b->lock);
    *success = true;

    for (i = 0; i < BUCKET_NITEMS; i++) {
        if (b->items[i] != NULL && b->hashes[i] == hv) {
            it = b->items[i];
            if (citem_key_matches(it, key, klen)) {
                goto done;
            }
        }
    }
    it = b->items[BUCKET_NITEMS - 1];
    if (it != NULL) {
        it = it->next;
        while (it != NULL && !citem_hkey_matches(it, key, klen, hv)) {
            it = it->next;
        }
    }

done:
#ifdef DEBUG
    printf("cache_get: key = %d, hash = %d, it = %p\n", *((int*) key), hv, it);
#endif
    if(it == NULL)
        lock_unlock(&b->lock);

#ifdef HIT_RATE
    if(it) hit++;
    if(total == 1000000) {
      printf("hit rate = %f\n", 1.0*hit/total);
      hit = 0; total = 0;
    }
#endif
    return it;
}


static citem *cache_put(cache_bucket *buckets, int nbuckets, citem *nit, bool replace, bool* success)
{
    citem *it, *prev;
    size_t i, di;
    bool has_direct = false;
    uint32_t hv = nit->hv;
    void *key = citem_key(nit);
    size_t klen = nit->keylen;
    nit->evicted = 1;

    int *val = citem_value(nit);
#ifdef DEBUG
    printf("cache_put: hash = %d, key = %d, val = %d, it = %p\n", hv, *((int*) key), *val, nit);
#endif

    cache_bucket *b = buckets + (hv % nbuckets);
    lock_lock(&b->lock);
    *success = true;
    //printf("lock\n");

    // Check if we need to replace an existing item
    for (i = 0; i < BUCKET_NITEMS; i++) {
        if (b->items[i] == NULL) {
            has_direct = true;
            di = i;
        } else if (b->hashes[i] == hv) {
            it = b->items[i];
            if (citem_key_matches(it, key, klen)) {
                assert(nit != it);
                nit->next = it->next;
                b->items[i] = nit;
#ifdef DEBUG
                printf("free %p\n", it);
#endif
                free(it);
                nit->bucket = b;
                return nit;
            }
        }
    }

    // Note it does not match, otherwise we would have already bailed in the for
    // loop
    it = b->items[BUCKET_NITEMS - 1];
    if (it != NULL) {
        prev = it;
        it = it->next;
        while (it != NULL && !citem_hkey_matches(it, key, klen, hv)) {
            prev = it;
            it = it->next;
        }

        if (it != NULL) {
            nit->next = it->next;
            prev->next = nit;
#ifdef DEBUG
            printf("free %p\n", it);
#endif
            free(it);
            nit->bucket = b;
            return nit;
        }
    }

    // We did not find an existing entry to replace, just stick it in wherever
    // we find room

    if(has_direct) {
        nit->next = b->items[di];
        b->hashes[di] = hv;
        b->items[di] = nit;
        nit->bucket = b;
        return nit;
    }

    if(replace) {
        citem *evict;
        // evict
        di = b->replace;
        b->replace = (b->replace + 1) % BUCKET_NITEMS;
        evict = b->items[di];
        evict->evicted |= 2;
        b->items[di] = NULL;

        nit->next = b->items[di];
        b->hashes[di] = hv;
        b->items[di] = nit;
        nit->bucket = b;
#ifdef DEBUG
        printf("insert & evict %p , flag = %d\n", evict, evict->evicted);
#endif
        return evict;
    }

    lock_unlock(&b->lock);
#ifdef DEBUG
        printf("insert fail (no replace)\n");
#endif
    return NULL;
}

static citem *cache_put_or_get(cache_bucket *buckets, int nbuckets, citem *nit, bool replace, bool* success)
{
    citem *it, *prev;
    size_t i, di;
    bool has_direct = false;
    uint32_t hv = nit->hv;
    void *key = citem_key(nit);
    size_t klen = nit->keylen;
    nit->evicted = 0;

    int *val = citem_value(nit);
#ifdef DEBUG
    printf("cache_put_get: hash = %d, key = %d, val = %d, it = %p\n", hv, *((int*) key), *val, nit);
#endif

    cache_bucket *b = buckets + (hv % nbuckets);
    lock_lock(&b->lock);
    *success = true;
    //printf("lock\n");

    // Check if we need to replace an existing item
    for (i = 0; i < BUCKET_NITEMS; i++) {
        if (b->items[i] == NULL) {
            has_direct = true;
            di = i;
        } else if (b->hashes[i] == hv) {
            it = b->items[i];
            if (citem_key_matches(it, key, klen)) {
                if(nit == it) printf("assert fail: nit = %p, it = %p\n", nit, it);
                assert(nit != it);
                //nit->next = it->next;
                //b->items[i] = nit;
#ifdef DEBUG
                printf("exist %p\n", it);
#endif
                free(nit);
                return it;
            }
        }
    }

    // Note it does not match, otherwise we would have already bailed in the for
    // loop
    it = b->items[BUCKET_NITEMS - 1];
    if (it != NULL) {
        prev = it;
        it = it->next;
        while (it != NULL && !citem_hkey_matches(it, key, klen, hv)) {
            prev = it;
            it = it->next;
        }

        if (it != NULL) {
            //nit->next = it->next;
            //prev->next = nit;
#ifdef DEBUG
            printf("exist %p\n", it);
#endif
            free(nit);
            return it; // need to release later
        }
    }

    // We did not find an existing entry to replace, just stick it in wherever
    // we find room
    if(has_direct) {
        nit->next = b->items[di];
        b->hashes[di] = hv;
        b->items[di] = nit;
        nit->bucket = b;
        lock_unlock(&b->lock);
#ifdef DEBUG
        printf("insert success %p\n", nit);
#endif
        return NULL;
    }

    if(replace) {
        citem *evict;
        // evict
        di = b->replace;
        b->replace = (b->replace + 1) % BUCKET_NITEMS;
        evict = b->items[di];
        evict->evicted |= 2;
        b->items[di] = NULL;

        nit->next = b->items[di];
        b->hashes[di] = hv;
        b->items[di] = nit;
        nit->bucket = b;
        //lock_unlock(&b->lock);
#ifdef DEBUG
        printf("insert & evict %p , flag = %d\n", evict, evict->evicted);
#endif
        return evict;
    }

done:
    lock_unlock(&b->lock);
#ifdef DEBUG
    printf("insert fail %p\n", nit);
#endif
    return NULL;
}

static void cache_delete(cache_bucket *buckets, int nbuckets, void* key, int klen, uint32_t hv, bool* success)
{
    citem *it, *prev;
    size_t i, di;

#ifdef DEBUG
    printf("cache_delete: hash = %d, key = %d\n", hv, *((int*) key));
#endif

    cache_bucket *b = buckets + (hv % nbuckets);
    lock_lock(&b->lock);
    *success = true;
    //printf("lock\n");

    // Check if we need to replace an existing item
    for (i = 0; i < BUCKET_NITEMS; i++) {
        if (b->items[i] && b->hashes[i] == hv) {
            it = b->items[i];
            if (citem_key_matches(it, key, klen)) {
	      //printf("delete %p\n", it);
                b->items[i] = it->next;
                if(b->items[i]) b->hashes[i] = b->items[i]->hv;
                free(it);
                goto done;
            }
        }
    }

    // Note it does not match, otherwise we would have already bailed in the for
    // loop
    it = b->items[BUCKET_NITEMS - 1];
    if (it != NULL) {
        prev = it;
        it = it->next;
        while (it != NULL && !citem_hkey_matches(it, key, klen, hv)) {
            prev = it;
            it = it->next;
        }

        if (it != NULL) {
	  //printf("delete %p\n", it);
            prev->next = it->next;
            free(it);
            goto done;
        }
    }


done:
    lock_unlock(&b->lock);
}

static inline void cache_release(citem *it) {
    if(it) {
        //printf("unlock %p\n", it);
        lock_unlock(&it->bucket->lock);
        //printf("unlock done %p\n", it);
    }
}

#endif
